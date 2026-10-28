"""One sequence, independent camera profiles, bounded parallel JSON generation."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock
import time

import numpy as np

from north16.annotations.estimation import estimate_parameters
from north16.annotations.profiles import DEFAULT_PROFILE, profile_hash, validate_profile
from north16.annotations.xanylabeling import save_json
from north16.common.files import local_path
from north16.layout.paths import label_path
from north16.packages import refresh_package

THRESHOLDS = ("water_definite_brightness_max", "water_probable_brightness_max", "ice_definite_brightness_min")


def camera_inputs(builder, sequence, *, cameras=None, profiles=None, limit=None, workers=4):
    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("并发数应为1–16")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("每镜头limit必须为正整数")
    builder.workspace.assert_unchanged()
    keys=[key for key in builder.workspace.keys() if key[0] == sequence]
    if cameras is not None:
        if not cameras or len(cameras) != len(set(cameras)):
            raise ValueError("镜头选择不能为空或重复")
        if set(cameras)-{key[2] for key in keys}:
            raise ValueError("所选镜头不在当前片段的visible索引中")
        keys=[key for key in keys if key[2] in cameras]
    if not keys:raise ValueError("该片段没有可见光相机图片")
    profiles=profiles or {}
    if set(profiles)-{key[2] for key in keys}:raise ValueError("参数包含未选择的镜头")
    result=[]
    for key in keys:
        images=builder.workspace.images(key)
        if limit:images=images[:limit]
        if not images:raise ValueError(f"镜头无图片：{key[2]}")
        result.append(dict(key=key,images=images,
                           profile=validate_profile(profiles.get(key[2],DEFAULT_PROFILE)),
                           profile_source="camera_profile" if key[2] in profiles else "default_unconfirmed"))
    return result


def estimate_camera(item, *, keep_horizon=True, cancel=None):
    base=deepcopy(item["profile"])
    images=item["images"]
    samples=[images[i] for i in sorted({0,len(images)//2,len(images)-1})]
    estimates=[];errors=[]
    for image in samples:
        if cancel and cancel.is_set():return None
        try:
            profile,evidence=estimate_parameters(image,base,keep_horizon=keep_horizon)
            estimates.append((profile,evidence))
        except Exception as exc:
            errors.append(dict(image=str(image),error=f"{type(exc).__name__}: {exc}"))
    if cancel and cancel.is_set():return None
    if not estimates:raise ValueError(f"{item['key'][2]}所有抽样图估计失败：{errors}")
    profile=deepcopy(base)
    warnings=[]
    majority=len(samples)//2+1
    if not keep_horizon:
        candidates=[p["horizon_normalized_xy"] for p,r in estimates if r["horizon"]["status"] == "suggested"]
        if len(candidates) >= majority and np.max(np.ptp(np.array(candidates)[:,:,1],axis=0)) <= .035:
            profile["horizon_normalized_xy"]=np.median(np.array(candidates),axis=0).tolist()
            horizon_status="suggested"
            warnings.append("地平线为多帧启发式候选，仍需逐镜头检查")
        else:
            horizon_status="retained"
            warnings.append("地平线证据不足或多帧不一致，保留该镜头基础线")
    else:
        horizon_status="preserved"
    if not keep_horizon:
        # Thresholds must use the final camera line, including when proposed
        # horizons were rejected by the multi-frame consistency check.
        brightness_estimates=[]
        for _,evidence in estimates:
            if cancel and cancel.is_set():return None
            try:
                p,r=estimate_parameters(evidence["source_image"],profile,keep_horizon=True)
                r["initial_horizon_candidate"]=evidence["horizon"]
                brightness_estimates.append((p,r))
            except Exception as exc:
                errors.append(dict(image=evidence["source_image"],error=f"{type(exc).__name__}: {exc}"))
        estimates=brightness_estimates
        if not estimates:raise ValueError("最终地平线下的阈值抽样全部失败")
    accepted=[p for p,r in estimates if r["brightness"]["status"] == "suggested"]
    if base["sea_mode"] != "mixed":
        brightness_status="skipped"
    elif (len(accepted) >= majority and
          max(np.ptp([p[k] for p in accepted]) for k in THRESHOLDS) <= 35):
        for k in THRESHOLDS:profile[k]=int(np.median([p[k] for p in accepted]))
        brightness_status="suggested"
    else:
        brightness_status="retained"
        warnings.append("冰水阈值证据不足或跨帧变化超过35灰度级，保留该镜头原值；请检查全冰/全水及光照变化")
    if item["profile_source"] == "default_unconfirmed":
        warnings.append("未提供该镜头的独立配置；基础地平线来自默认值，尚未人工确认")
    if len(samples) < 3:warnings.append("不足3张抽样图，时间一致性验证有限")
    if errors:warnings.append("部分抽样图估计失败，详见sample_errors")
    profile=validate_profile(profile)
    report=dict(method="per_camera_three_frame_consensus_v1",camera=item["key"][2],sequence=item["key"][0],
                sensor="visible",profile_source=item["profile_source"],profile_sha256=profile_hash(profile),
                base_profile_sha256=profile_hash(base),sample_count=len(samples),
                samples=[r for _,r in estimates],sample_errors=errors,
                horizon=dict(status=horizon_status,keep_current=keep_horizon,review_status="unreviewed"),
                brightness=dict(status=brightness_status,accepted_samples=len(accepted),
                                required_samples=majority,max_threshold_spread=35),warnings=warnings,
                review_status="unreviewed",caveat="亮度分组不等于冰水真值；不自动识别薄冰、other或全冰/全水")
    return dict(camera=item["key"][2],profile=profile,estimation=report)


def estimate_cameras(builder, sequence, *, cameras=None, profiles=None, workers=4,
                     keep_horizon=True, limit=None, cancel=None, progress=None):
    items=camera_inputs(builder,sequence,cameras=cameras,profiles=profiles,limit=limit,workers=workers)
    cancel=cancel if cancel is not None else Event()
    results=[];errors=[]
    with ThreadPoolExecutor(max_workers=min(workers,len(items)),thread_name_prefix="north16-estimate") as pool:
        futures={pool.submit(estimate_camera,item,keep_horizon=keep_horizon,cancel=cancel):item for item in items}
        for done,future in enumerate(as_completed(futures),1):
            item=futures[future]
            try:
                result=future.result()
                if result is not None:results.append(result)
            except Exception as exc:errors.append(dict(camera=item["key"][2],error=f"{type(exc).__name__}: {exc}"))
            if progress:progress(done,len(items),"估参 · "+item["key"][2])
    return dict(status="cancelled" if cancel.is_set() else "completed_with_errors" if errors else "succeeded",
                sequence=sequence,cameras=sorted(results,key=lambda r:r["camera"]),errors=errors,
                expected=len(items),succeeded=len(results),failed=len(errors),workers=min(workers,len(items)))


def generate_cameras(builder, sequence, output, *, cameras=None, profiles=None, workers=4,
                     estimate=True, keep_horizon=True, limit=None, cancel=None, progress=None, estimations=None):
    items=camera_inputs(builder,sequence,cameras=cameras,profiles=profiles,limit=limit,workers=workers)
    cancel=cancel if cancel is not None else Event()
    total=sum(len(item["images"]) for item in items)
    state_lock=Lock();completed=0
    started=time.monotonic();run_id=builder.workspace.new_run_id()
    with builder._package(output) as output:
        # Fail the entire request before writing labels if any target exists.
        # This also protects labels manually edited since a preceding run.
        for item in items:
            for image in item["images"]:
                dest=local_path(builder.payload_root(output),label_path(image.relative_to(builder.root).as_posix()).as_posix())
                if dest.exists():raise FileExistsError(f"标签已存在，保留人工修改；请选择新标签包：{dest}")
        def camera_job(item):
            nonlocal completed
            camera=item["key"][2];expected=len(item["images"])
            if cancel.is_set():
                return dict(camera=camera,status="cancelled",expected=expected,succeeded=0,failed=0,errors=[],labels=[])
            result=None
            try:
                prepared=builder._prepare(item["key"],item["images"],item["profile"])
                if estimate:
                    result=estimate_camera(item,keep_horizon=keep_horizon,cancel=cancel)
                    if result is None:
                        return dict(camera=camera,status="cancelled",expected=expected,succeeded=0,failed=0,errors=[],labels=[])
                    prepared["profile"]=result["profile"]
                else:
                    evidence=(estimations or {}).get(camera)
                    if evidence and evidence.get("profile_sha256") != profile_hash(prepared["profile"]):
                        evidence=None  # Manual edits must not inherit stale estimation provenance.
                    result=dict(camera=camera,profile=prepared["profile"],estimation=evidence)
                path=output/"parameters"/sequence/"visible"/(camera+"_"+run_id+".json")
                save_json(path,result["profile"])
                if result["estimation"] is not None:
                    save_json(path.with_suffix(".estimation.json"),result["estimation"])
                def update(done,count,name):
                    nonlocal completed
                    with state_lock:
                        completed+=1
                        if progress:progress(completed,total,f"{camera} · {done}/{count} · {name}")
                report=builder._generate_stream(prepared,output,cancel=cancel,progress=update,
                                                estimation=result["estimation"],internal_threads=1)
                report.update(result,parameters_file=path.relative_to(output).as_posix())
                return report
            except Exception as exc:
                with state_lock:
                    completed+=expected
                    if progress:progress(completed,total,camera+" · 失败")
                return dict(camera=camera,status="failed",expected=expected,succeeded=0,failed=expected,
                            errors=[dict(camera=camera,error=f"{type(exc).__name__}: {exc}")],labels=[])
        with ThreadPoolExecutor(max_workers=min(workers,len(items)),thread_name_prefix="north16-camera") as pool:
            futures=[pool.submit(camera_job,item) for item in items]
            reports=[future.result() for future in as_completed(futures)]
        reports.sort(key=lambda r:r["camera"])
        errors=[e for r in reports for e in r["errors"]]
        report=dict(status="cancelled" if cancel.is_set() else "completed_with_errors" if errors else "succeeded",
                    sequence=sequence,sensor="visible",workers=min(workers,len(items)),internal_threads=1,
                    expected=total,succeeded=sum(r["succeeded"] for r in reports),failed=sum(r["failed"] for r in reports),
                    unprocessed=total-sum(r["succeeded"]+r["failed"] for r in reports),
                    errors=errors,labels=[p for r in reports for p in r["labels"]],cameras=reports,
                    format="json",label_status="draft",review_status="unreviewed",output=str(output),
                    automatic_estimation=estimate,elapsed_seconds=round(time.monotonic()-started,2))
        # Workers never touch the shared manifests. Publish once after joining.
        builder.finish_output(output)
        save_json(output/"last_run.json",report)
        save_json(output/("run_"+run_id+".json"),report)
        return report
