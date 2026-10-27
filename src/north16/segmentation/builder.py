"""Generate editable labels directly under portable sequences/.../masks/*.json."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from PIL import Image

from north16.common.files import local_path, read_info, sha256, write_info
from north16.packages import refresh_package, export_files
from north16.layout.paths import label_path
from .labels import render, validate_label


class SegmentationBuilder:
    def __init__(self, root):
        from north16.annotations.dataset_workspace import DatasetWorkspace
        self.workspace=DatasetWorkspace(root)
        self.root=self.workspace.root

    def _prepare(self, key, images, profile):
        from north16.annotations.profiles import validate_profile
        profile=validate_profile(profile)
        images=[Path(p).resolve(strict=True) for p in images]
        observations,context=self.workspace.prepare(key,images)
        return dict(key=key,images=images,profile=profile,observations=observations,context=context)

    def _destinations(self, images, observations, output):
        destinations=[]
        for image in images:
            dest=local_path(output/"dataset",label_path(observations[str(image)]["image"]).as_posix())
            if dest.exists():raise FileExistsError(f"标签已存在，保留人工修改：{dest}")
            destinations.append(dest)
        return destinations

    def _package(self, output):
        from contextlib import contextmanager
        @contextmanager
        def locked():
            output_path=Path(output).resolve()
            if output_path==self.root or output_path.is_relative_to(self.root) or self.root.is_relative_to(output_path):
                raise ValueError("标签包必须保存到数据集之外；生成后整包复制或导入")
            header=output_path/"package.txt"
            if output_path.exists() and not header.is_file():
                raise FileExistsError("输出目录已存在且不是标签包")
            expected=dict(schema_version="north16_package_v1",kind="segmentation",protocol_id=self.workspace.protocol["protocol_id"])
            output_path.mkdir(parents=True,exist_ok=True)
            lock=output_path/".segmentation.lock"
            try:
                with lock.open("x",encoding="utf-8") as handle:handle.write("generate\n")
            except FileExistsError as exc:
                raise FileExistsError("该标签包正在被其他任务使用，请等待或选择新包") from exc
            try:
                if header.exists() and read_info(header)!=expected:raise ValueError("已有输出包不兼容")
                write_info(header,expected)
                yield output_path
            finally:
                lock.unlink(missing_ok=True)
        return locked()

    def _generate_stream(self, prepared, output, *, cancel=None, progress=None, estimation=None, internal_threads=4):
        from north16.annotations.profiles import profile_hash
        from north16.annotations.workspace import preview,segmentation_method
        from north16.annotations.xanylabeling import vectorize,save_json
        images,profile,observations,context=[prepared[k] for k in ("images","profile","observations","context")]
        destinations=self._destinations(images,observations,output)
        records=[];errors=[];cancelled=False
        for index,(image,dest) in enumerate(zip(images,destinations)):
            if cancel and cancel.is_set():cancelled=True;break
            row=observations[str(image)]
            try:
                mask=preview(image,profile,internal_threads=internal_threads)
                if cancel and cancel.is_set():cancelled=True;break
                if sha256(image)!=row["image_sha256"]:raise ValueError("原图处理期间发生变化")
                data=dict(version="4.0.0",flags={},shapes=vectorize(mask),imagePath="../images/"+image.name,
                          imageData=None,imageWidth=mask.shape[1],imageHeight=mask.shape[0],checked=False,
                          north16=dict(id=row["id"],image=row["image"],image_sha256=row["image_sha256"],
                                       protocol_id=context["protocol_id"],label_status="draft",review_status="unreviewed",
                                       method=segmentation_method(profile),parameters=profile,profile_sha256=profile_hash(profile),
                                       generated_at=datetime.now(timezone.utc).isoformat()))
                if estimation is not None:data["north16"]["estimation"]=estimation
                if not np.array_equal(render(data),mask):raise ValueError("JSON像素还原不一致")
                # All destinations have been preflighted under the package lock.
                if dest.exists():raise FileExistsError(f"标签已存在：{dest}")
                save_json(dest,data)
                if not np.array_equal(render(json.loads(dest.read_text(encoding="utf-8"))),mask):
                    raise ValueError("JSON保存回读不一致")
                records.append(dest.relative_to(output).as_posix())
            except Exception as exc:
                errors.append(dict(image=str(image),error=f"{type(exc).__name__}: {exc}"))
            if progress:progress(index+1,len(images),image.name)
        return dict(status="cancelled" if cancelled else "completed_with_errors" if errors else "succeeded",
                    expected=len(images),succeeded=len(records),failed=len(errors),errors=errors,labels=records,
                    format="json",label_status="draft",review_status="unreviewed",output=str(output))

    def generate(self, key, images, profile, output, *, cancel=None, progress=None, estimation=None):
        from north16.annotations.xanylabeling import save_json
        prepared=self._prepare(key,images,profile)
        with self._package(output) as output:
            self._destinations(prepared["images"],prepared["observations"],output)
            report=self._generate_stream(prepared,output,cancel=cancel,progress=progress,estimation=estimation)
            refresh_package(output,kind="segmentation",protocol_id=self.workspace.protocol["protocol_id"])
            save_json(output/"last_run.json",report)
            return report

    def estimate_cameras(self, sequence, **kwargs):
        from .batch import estimate_cameras
        return estimate_cameras(self,sequence,**kwargs)

    def generate_cameras(self, sequence, output, **kwargs):
        from .batch import generate_cameras
        return generate_cameras(self,sequence,output,**kwargs)

    def export(self, output, *, sequences=None, sensor=None, cameras=None):
        files=[]
        for key in self.workspace.keys(None):
            if (sequences and key[0] not in sequences) or (sensor and key[1]!=sensor) or (cameras and key[2] not in cameras):continue
            for row in self.workspace.streams[key]:
                image=local_path(self.root,row["image"])
                label=image.parent.parent/"masks"/(image.stem+".json")
                if label.is_file():
                    validate_label(label,image,root=self.root,expected_id=row["id"])
                    files.append(label)
        return export_files(self.root,output,files,kind="segmentation")


def generate_folder(images, profile, output, *, cancel=None, progress=None):
    """Plain-folder compatibility: one images/ folder and one masks/JSON folder."""
    import shutil
    from north16.annotations.workspace import check_output,preview
    from north16.annotations.profiles import validate_profile
    from north16.annotations.xanylabeling import vectorize,save_json
    images=[Path(p).resolve(strict=True) for p in images]
    output=check_output(images,output);profile=validate_profile(profile)
    output.mkdir(parents=True)
    records=[];errors=[];cancelled=False
    for index,image in enumerate(images):
        if cancel and cancel.is_set():cancelled=True;break
        try:
            mask=preview(image,profile)
            if cancel and cancel.is_set():cancelled=True;break
            stem=f"{index:06d}_{image.stem}"
            copied=output/"images"/(stem+image.suffix.lower())
            copied.parent.mkdir(exist_ok=True)
            shutil.copyfile(image,copied)
            data=dict(version="4.0.0",flags={},shapes=vectorize(mask),imagePath="../images/"+copied.name,
                      imageData=None,imageWidth=mask.shape[1],imageHeight=mask.shape[0],checked=False,
                      north16=dict(source_image=str(image),image_sha256=sha256(image),label_status="draft",parameters=profile))
            if not np.array_equal(render(data),mask):raise ValueError("JSON像素还原不一致")
            target=output/"masks"/(stem+".json");save_json(target,data);records.append(str(target))
        except Exception as exc:errors.append(dict(image=str(image),error=str(exc)))
        if progress:progress(index+1,len(images),image.name)
    report=dict(status="cancelled" if cancelled else "completed_with_errors" if errors else "succeeded",
                expected=len(images),succeeded=len(records),failed=len(errors),errors=errors,format="json",
                labels=records,label_status="draft",review_status="unreviewed")
    save_json(output/"last_run.json",report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("gui","generate","batch","estimate","export"))
    parser.add_argument("--root",required=True);parser.add_argument("--output")
    parser.add_argument("--sequence");parser.add_argument("--sensor",choices=("visible","infrared"))
    parser.add_argument("--camera");parser.add_argument("--profile");parser.add_argument("--limit",type=int)
    parser.add_argument("--workers",type=int,default=4,help="batch/estimate并发镜头数，1–16，默认4")
    parser.add_argument("--profiles",help="独立镜头配置目录：<camera>.json")
    parser.add_argument("--no-estimate",action="store_true",help="batch直接使用各镜头配置，不重新估参")
    parser.add_argument("--auto-horizon",action="store_true",help="尝试多帧地平线候选；默认保留各镜头基础线")
    args=parser.parse_args(argv)
    if args.action=="gui":
        from north16.gui.app import main as gui
        return gui(["--dataset",args.root])
    if args.action!="estimate" and not args.output:parser.error("generate/batch/export requires --output")
    builder=SegmentationBuilder(args.root)
    if args.action in {"batch","estimate"}:
        if not args.sequence:parser.error("batch/estimate requires --sequence")
        if args.sensor=="infrared":parser.error("batch/estimate目前只支持visible")
        if args.profile:parser.error("batch/estimate请用--profiles提供各镜头独立配置")
        from north16.annotations.profiles import load_profile
        profiles={}
        if args.profiles:
            folder=Path(args.profiles).resolve(strict=True)
            if not folder.is_dir():parser.error("--profiles必须为目录")
            keys=[key for key in builder.workspace.keys() if key[0]==args.sequence and (not args.camera or key[2]==args.camera)]
            for key in keys:
                path=folder/(key[2]+".json")
                if path.is_file():profiles[key[2]]=load_profile(path)
        options=dict(cameras=[args.camera] if args.camera else None,profiles=profiles,workers=args.workers,
                     keep_horizon=not args.auto_horizon,limit=args.limit)
        if args.action=="estimate":report=builder.estimate_cameras(args.sequence,**options)
        else:report=builder.generate_cameras(args.sequence,args.output,estimate=not args.no_estimate,**options)
    elif args.action=="export":
        report=builder.export(args.output,sequences=[args.sequence] if args.sequence else None,sensor=args.sensor,
                              cameras=[args.camera] if args.camera else None)
    else:
        if not args.sequence or not args.camera or not args.profile:parser.error("generate requires --sequence --camera --profile")
        if args.limit is not None and args.limit<=0:parser.error("--limit must be positive")
        from north16.annotations.profiles import load_profile
        key=(args.sequence,args.sensor or "visible",args.camera)
        images=builder.workspace.images(key)
        report=builder.generate(key,images[:args.limit] if args.limit else images,load_profile(args.profile),args.output)
    print(json.dumps(report,ensure_ascii=False,indent=2))
