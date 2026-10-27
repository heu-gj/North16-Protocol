"""Package payload is always dataset/sequences/...; never replace global indices."""
import argparse
import json
from pathlib import Path
import shutil

from north16.common.files import local_path, read_info, read_table, sha256, write_info, write_table


def refresh_package(output, *, kind, protocol_id):
    output = Path(output).resolve()
    existing = output/"package.txt"
    expected = dict(schema_version="north16_package_v1", kind=kind, protocol_id=protocol_id)
    if existing.exists() and read_info(existing) != expected:
        raise ValueError("输出目录已有不同类型或协议的数据包")
    write_info(existing, expected)
    files = [p for p in (output/"dataset").rglob("*") if p.is_file()]
    write_table(output/"files.txt", ("path", "sha256"), [dict(path=p.relative_to(output/"dataset").as_posix(),sha256=sha256(p)) for p in sorted(files)])
    (output/"README.txt").write_text("将dataset中的内容整体合并到数据集根目录。也可执行：\n"
        "north16 import-package --root <数据集根目录> --package <本目录>\n"
        "不覆盖内容不同的已有文件；JSON默认是未审核草稿。\n",encoding="utf-8")
    return dict(root=str(output), kind=kind, files=len(files))


def export_files(root, output, files, *, kind):
    root, output = Path(root).resolve(strict=True), Path(output).resolve()
    if output.exists():raise FileExistsError("导出要求新目录")
    if output==root or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("导出包必须与数据集分开")
    files=list(files)
    if not files:raise ValueError("没有可导出的文件")
    for source in files:
        source=source.resolve(strict=True)
        relative=source.relative_to(root).as_posix()
        dest=local_path(output/"dataset",relative)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
        if sha256(source)!=sha256(dest):raise ValueError("复制校验失败")
    return refresh_package(output,kind=kind,protocol_id=read_info(root/"protocol.txt")["protocol_id"])


def import_package(root, package):
    root, package=Path(root).resolve(strict=True),Path(package).resolve(strict=True)
    info=read_info(root/"info.txt");header=read_info(package/"package.txt")
    if info.get("dataset_status")!="working" or header.get("schema_version")!="north16_package_v1" or header.get("kind") not in ("camera","segmentation") or header.get("protocol_id")!=info["protocol_id"]:
        raise ValueError("不兼容或冻结的数据集/数据包")
    rows=read_table(package/"files.txt");pending=[];seen=set()
    for row in rows:
        relative=row["path"]
        if relative.casefold() in seen:raise ValueError("数据包路径重复")
        seen.add(relative.casefold())
        source=local_path(package/"dataset",relative);dest=local_path(root,relative)
        parts=Path(relative).parts
        if len(parts)<5 or parts[0]!="sequences" or parts[2] not in ("visible","infrared"):
            raise ValueError("本版仅支持规范相机流的数据包")
        if header["kind"]=="segmentation" and (len(parts)!=6 or parts[4]!="masks" or source.suffix!=".json"):
            raise ValueError("分割包只允许masks/*.json")
        if header["kind"]=="camera":
            allowed=(len(parts)==5 and parts[4] in ("info.txt","frames.txt")) or (len(parts)==6 and
                     ((parts[4]=="images" and source.suffix==".png") or (parts[4]=="meta" and source.suffix==".txt")))
            if not allowed:raise ValueError("相机包仅允许info/frames/images/meta")
            stream=root/Path(*parts[:4])
            if not (stream/"info.txt").is_file():raise ValueError("目标相机流未初始化")
            source_info=read_info(package/"dataset"/Path(*parts[:4])/"info.txt")
            target_info=read_info(stream/"info.txt")
            if any(source_info.get(k)!=target_info.get(k) for k in ("source_id","source_sha256")):
                raise ValueError("相机包来源与初始化记录不一致")
        if sha256(source)!=row["sha256"]:raise ValueError("数据包校验失败")
        if header["kind"]=="segmentation":
            from north16.segmentation.labels import validate_label
            image=root/Path(*parts[:4])/"images"/(source.stem+".png")
            validate_label(source,image,root=root)
        replace_pending=False
        if dest.exists() and sha256(dest)!=row["sha256"]:
            if header["kind"]=="camera" and dest.name=="info.txt" and len(parts)==5:
                old,new=read_info(dest),read_info(source)
                replace_pending=(old.get("decode_status")=="pending" and new.get("decode_status")=="complete" and
                                 old.get("source_id")==new.get("source_id") and old.get("source_sha256")==new.get("source_sha256"))
            if not replace_pending:raise FileExistsError(f"内容冲突，未覆盖：{dest}")
        if not dest.exists() or replace_pending:pending.append((source,dest,replace_pending))
    actual={p.relative_to(package/"dataset").as_posix().casefold() for p in (package/"dataset").rglob("*") if p.is_file()}
    if actual!=seen:raise ValueError("包内存在未登记或缺失文件")
    if header["kind"]=="camera":
        from north16.preprocess.camera import verify_stream
        folders={tuple(Path(r["path"]).parts[:4]) for r in rows}
        for parts in folders:
            folder=package/"dataset"/Path(*parts)
            stream_info=read_info(folder/"info.txt")
            verify_stream(folder,key=stream_info["extraction_key"],source_id=stream_info["source_id"],deep=True)
    # All conflicts/hashes checked before copying. Do not modify root samples.txt.
    for source,dest,_ in pending:
        dest.parent.mkdir(parents=True,exist_ok=True)
        temporary=dest.with_suffix(dest.suffix+".partial")
        if temporary.exists():raise FileExistsError(temporary)
        shutil.copyfile(source,temporary)
        if sha256(temporary)!=sha256(source):raise ValueError("导入复制校验失败")
        temporary.replace(dest)
    return dict(status="succeeded",copied=len(pending),skipped=len(rows)-len(pending))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",required=True);parser.add_argument("--package",required=True)
    args=parser.parse_args(argv)
    print(json.dumps(import_package(args.root,args.package),ensure_ascii=False,indent=2))
