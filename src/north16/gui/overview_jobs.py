"""Read-only parallel camera previews, without Qt objects or label output."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import hashlib
from threading import Event

from PIL import Image

from north16.annotations.profiles import profile_hash
from north16.annotations.workspace import colored,preview,read_image
from north16.common.files import sha256
from north16.segmentation.batch import camera_inputs


def preview_result(image,source,mask,profile,checksum):
    source=source.copy();source.thumbnail((480,270))
    color=colored(mask);color=color.resize(source.size,Image.Resampling.NEAREST)
    return dict(image=str(image),image_name=image.name,source_image_sha256=checksum,
                profile_sha256=profile_hash(profile),mask=mask,
                source=source,color=color,overlay=Image.blend(source,color,.42))


def _preview_image(builder,item,image):
    prepared=builder._prepare(item["key"],[image],item["profile"])
    source=read_image(image)
    mask=preview(image,item["profile"],internal_threads=1)
    checksum=prepared["observations"][str(image)]["image_sha256"]
    if sha256(image)!=checksum:raise ValueError("原图预览期间发生变化")
    return preview_result(image,source,mask,item["profile"],checksum)


def preview_cameras(builder,sequence,*,profiles=None,workers=4,frame_index=0,cancel=None,progress=None):
    if type(frame_index) is not int or frame_index<0:raise ValueError("预览帧序号应为非负整数")
    items=camera_inputs(builder,sequence,profiles=profiles,workers=workers)
    cancel=cancel if cancel is not None else Event()
    def compute(item):
        if cancel.is_set():return None
        image=item["images"][min(frame_index,len(item["images"])-1)]
        result=_preview_image(builder,item,image)
        if cancel.is_set():return None
        return dict(camera=item["key"][2],requested_frame_index=frame_index,**result)
    results=[];errors=[]
    with ThreadPoolExecutor(max_workers=min(workers,len(items)),thread_name_prefix="north16-preview") as pool:
        futures={pool.submit(compute,item):item for item in items}
        for done,future in enumerate(as_completed(futures),1):
            camera=futures[future]["key"][2]
            try:
                result=future.result()
                if result is not None:results.append(result)
            except Exception as exc:errors.append(dict(camera=camera,error=f"{type(exc).__name__}: {exc}"))
            if progress:progress(done,len(items),"预览 · "+camera)
    return dict(status="cancelled" if cancel.is_set() else "completed_with_errors" if errors else "succeeded",
                cameras=sorted(results,key=lambda r:r["camera"]),errors=errors,expected=len(items),
                succeeded=len(results),failed=len(errors))


def validate_camera_samples(builder,sequence,*,profiles=None,workers=4,cancel=None,progress=None):
    """Validate three positions per camera, decoding duplicate short-stream frames once.

    Only thumbnails and hash receipts are retained; no full-resolution mask cache
    or label file is produced by this read-only validation operation.
    """
    items=camera_inputs(builder,sequence,profiles=profiles,workers=workers)
    cancel=cancel if cancel is not None else Event()
    total=sum(len({0,len(item["images"])//2,len(item["images"])-1}) for item in items)
    def compute(item):
        images=item["images"];indices=[0,len(images)//2,len(images)-1]
        results={}
        for index in sorted(set(indices)):
            if cancel.is_set():break
            image=images[index]
            try:
                result=_preview_image(builder,item,image)
                if cancel.is_set():break
                result["mask_sha256"]=hashlib.sha256(result.pop("mask").tobytes()).hexdigest()
                result["status"]="succeeded"
            except Exception as exc:
                result=dict(image=str(image),image_name=image.name,status="failed",error=f"{type(exc).__name__}: {exc}")
            results[index]=result
        samples=[dict(position=position,frame_index=index,
                      result=results.get(index,dict(image=str(images[index]),image_name=images[index].name,status="unprocessed")))
                 for position,index in zip(("start","middle","end"),indices)]
        return dict(camera=item["key"][2],profile=deepcopy(item["profile"]),profile_sha256=profile_hash(item["profile"]),
                    samples=samples,unique_results=list(results.values()),unique_expected=len(set(indices)))
    results=[];completed=0
    with ThreadPoolExecutor(max_workers=min(workers,len(items)),thread_name_prefix="north16-samples") as pool:
        futures={pool.submit(compute,item):item for item in items}
        for future in as_completed(futures):
            result=future.result();results.append(result);completed+=len(result["unique_results"])
            if progress:progress(completed,total,"三帧验证 · "+result["camera"])
    errors=[dict(camera=r["camera"],image=s["image"],error=s["error"]) for r in results for s in r["unique_results"] if s["status"]=="failed"]
    succeeded=sum(s["status"]=="succeeded" for r in results for s in r["unique_results"])
    return dict(status="cancelled" if cancel.is_set() else "completed_with_errors" if errors else "succeeded",
                sequence=sequence,dataset_root=str(builder.root),cameras=sorted(results,key=lambda r:r["camera"]),
                expected=total,succeeded=succeeded,failed=len(errors),unprocessed=total-succeeded-len(errors),errors=errors,
                review_status="unreviewed")
