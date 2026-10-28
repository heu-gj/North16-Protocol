"""Keep decoded images and editable labels together before dataset delivery."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

from north16.common.files import local_path, read_info, read_table, write_info
from north16.layout import DatasetInitializer
from north16.packages import export_files
from north16.preprocess.camera import verify_stream
from north16.segmentation.builder import SegmentationBuilder
from north16.segmentation.labels import validate_label


def is_annotation(root):
    return read_info(Path(root)/"info.txt").get("workspace_role") == "annotation"


def builder_for(root):
    return AnnotationBuilder(root) if is_annotation(root) else SegmentationBuilder(root)


class AnnotationWorkspace:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not is_annotation(self.root):
            raise ValueError("请选择annotation initialize创建的标注工作区")

    @classmethod
    def initialize(cls, output, *, raw=None, dataset=None, segments=None):
        if (raw is None) == (dataset is None):
            raise ValueError("请指定raw或dataset，且仅指定一个")
        output = Path(output).resolve()
        if output.exists():
            raise FileExistsError("标注工作区要求新目录，不覆盖已有图片和标签")
        if raw is not None:
            DatasetInitializer().initialize(raw,output,segments=segments)
        else:
            source = Path(dataset).resolve(strict=True)
            if output.is_relative_to(source) or source.is_relative_to(output):
                raise ValueError("标注工作区与最终数据集目录必须分开")
            info = read_info(source/"info.txt")
            if info.get("dataset_status")!="working" or info.get("camera_index")!="frames":
                raise ValueError("需要initialize生成的working结构化数据集")
            if info.get("workspace_role")=="annotation":
                raise ValueError("--dataset应指向最终结构化数据集")
            sources = read_table(local_path(source,info.get("source_registry","sources.txt")))
            output.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="north16_annotation_",dir=output.parent) as tmp:
                stage=Path(tmp)/"workspace";stage.mkdir()
                for name in ("info.txt","protocol.txt","classes.txt"):
                    shutil.copy2(source/name,stage/name)
                from north16.layout.initialize import SOURCE_COLUMNS
                from north16.preprocess.index import SAMPLE_COLUMNS
                from north16.common.files import write_table
                write_table(stage/"sources.txt",SOURCE_COLUMNS,sources)
                write_table(stage/"samples.txt",SAMPLE_COLUMNS,[])
                for row in sources:
                    seq=local_path(stage,"sequences/"+row["sequence"])
                    seq.mkdir(parents=True,exist_ok=True)
                    if not (seq/"info.txt").exists():
                        shutil.copy2(source/"sequences"/row["sequence"]/"info.txt",seq/"info.txt")
                    if row["sensor"] not in ("visible","infrared"):
                        continue
                    stream=local_path(stage,f"sequences/{row['sequence']}/{row['sensor']}/{row['camera']}")
                    (stream/"images").mkdir(parents=True);(stream/"meta").mkdir()
                    write_info(stream/"info.txt",dict(schema_version="north16_camera_v1",source_id=row["source_id"],
                               source_sha256=row["sha256"],source_video_path=row["source_relative_path"],
                               sequence=row["sequence"],sensor=row["sensor"],camera=row["camera"],
                               decode_status="pending",decoded_frame_count=0))
                info.update(source_registry="sources.txt",sample_count=0,camera_status="initialized")
                # New workspace has no inherited attribute/run receipts.
                for name in ("attribute_registry","latest_camera_run"):
                    info.pop(name,None)
                write_info(stage/"info.txt",info)
                write_info(stage/"sync/info.txt",dict(association_status="unverified"))
                (stage/"logs").mkdir()
                stage.rename(output)
        info=read_info(output/"info.txt")
        info.update(workspace_role="annotation",annotation_storage="in_place_masks",sample_count=0)
        write_info(output/"info.txt",info)
        return dict(root=str(output),workspace_role="annotation",images=0,masks=0)

    def extract(self, **kwargs):
        from north16.camera import CameraBuilder
        return CameraBuilder(self.root).extract(**kwargs)

    def export(self, output, *, sequences=None, sensor=None, cameras=None, cancel=None, progress=None):
        """Export all images in selected complete streams, including unlabeled ones."""
        builder=AnnotationBuilder(self.root)
        files=[];streams=images=labels=0
        # Share the extraction/generation lock for a consistent read-only snapshot.
        with builder._package(self.root):
            for receipt in sorted(self.root.glob("sequences/*/*/*/frames.txt")):
                if cancel is not None and cancel.is_set():
                    return dict(status="cancelled",root=str(output),streams=0,images=0,labels=0,unlabeled_images=0)
                folder=receipt.parent;seq,kind,camera=folder.relative_to(self.root).parts[1:]
                if ((sequences and seq not in sequences) or (sensor and kind!=sensor) or
                        (cameras and camera not in cameras)):
                    continue
                info=read_info(folder/"info.txt")
                rows=verify_stream(folder,key=info["extraction_key"],source_id=info["source_id"])
                registered={Path(row['image']).stem for row in rows}
                masks=folder/"masks"
                if masks.exists() and any(p.is_file() and (p.suffix!='.json' or p.stem not in registered) for p in masks.iterdir()):
                    raise ValueError("masks中存在未登记的标签文件，请先核对")
                files.extend((folder/"info.txt",receipt));streams+=1
                for row in rows:
                    if cancel is not None and cancel.is_set():
                        return dict(status="cancelled",root=str(output),streams=0,images=0,labels=0,unlabeled_images=0)
                    image=local_path(self.root,row["image"])
                    meta=local_path(self.root,row["meta"])
                    files.extend((image,meta));images+=1
                    label=folder/"masks"/(image.stem+".json")
                    if label.exists():
                        validate_label(label,image,root=self.root,expected_id=row["id"])
                        files.append(label);labels+=1
            if not files:raise ValueError("所选范围没有已抽帧的完整镜头")
            report=export_files(self.root,output,files,kind="annotation",cancel=cancel,progress=progress)
        if report["status"]=="cancelled":
            streams=images=labels=0
        return dict(report,streams=streams,images=images,labels=labels,unlabeled_images=images-labels)


class AnnotationBuilder(SegmentationBuilder):
    def __init__(self,root):
        super().__init__(root)
        if not is_annotation(self.root):
            raise ValueError("就地标注仅支持annotation工作区")

    def payload_root(self,output):
        return self.root

    def finish_output(self,output):
        pass  # The working directory is not a delivery package.

    @contextmanager
    def _package(self,output):
        if Path(output).resolve()!=self.root:
            raise ValueError("标注工作区的JSON固定写入同镜头masks，不另建标签包")
        lock=self.root/".north16_build.lock"
        try:
            with lock.open("x",encoding="utf-8") as handle:handle.write("annotation\n")
        except FileExistsError as exc:
            raise FileExistsError("标注工作区正在抽帧、保存或导出，请稍后再试") from exc
        try:
            self.workspace.assert_unchanged()
            yield self.root
        finally:
            lock.unlink(missing_ok=True)
