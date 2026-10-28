"""Timestamp sampling without synthetic frames or lost source frame identities."""
from fractions import Fraction
import math
import re


SHOW = re.compile(r"\bn:\s*(\d+)\s+pts:\s*(\S+)\s+pts_time:\s*(\S+)")
TIME_BASE = re.compile(r"config in time_base:\s*(\d+/\d+)")


def normalize_interval(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("抽帧间隔应为大于0的有限秒数")
    try:
        interval = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("抽帧间隔应为大于0的有限秒数") from exc
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("抽帧间隔应为大于0的有限秒数")
    return interval


def video_filter(interval):
    if interval is None:
        return "format=rgb24,showinfo"
    # showinfo on both sides of a non-buffering select/format chain records the
    # source n even when PTS repeat. fps/setpts would lose this correspondence.
    return ("showinfo@source=checksum=0,"
            f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{interval!r})',"
            "format=rgb24,showinfo@selected")


def parse_sampled_log(text, interval):
    """Pair selected output with its immediate source record, fail on ambiguity."""
    source, selected, bases = [], [], {}
    for line in text.splitlines():
        role = "source" if "showinfo@source" in line else "selected" if "showinfo@selected" in line else None
        if role is None:
            continue
        base = TIME_BASE.search(line)
        if base:
            bases[role] = base[1]
        match = SHOW.search(line)
        if not match:
            continue
        n, pts, seconds = match.groups()
        if role == "source":
            if int(n) != len(source):
                raise ValueError("源解码帧序号不连续，无法确认抽帧身份")
            source.append((int(n), pts, seconds))
        else:
            if (not source or int(n) != len(selected) or (pts, seconds) != source[-1][1:] or
                    selected and source[-1][0] <= selected[-1][0]):
                raise ValueError("抽样帧与源解码帧的PTS对应关系不明确")
            selected.append(source[-1])
    if not selected or selected[0][0] != 0 or set(bases) != {"source", "selected"} or bases['source'] != bases['selected']:
        raise ValueError("抽样日志缺失，或时间基/首帧身份不一致")
    try:
        times = [int(pts)*Fraction(bases['source']) for _, pts, _ in source]
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("按秒抽帧需要有效的原始PTS和time_base") from exc
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError("源PTS倒退，无法按秒抽帧；请先检查视频时间戳")
    chosen = [times[n] for n, _, _ in selected]
    if any(float(b-a)+1e-9 < interval for a, b in zip(chosen, chosen[1:])):
        raise ValueError("抽样帧时间间隔小于请求值")
    return selected, bases['source'], len(source)


def estimated_count(stream, interval):
    count = stream.get('nb_frames')
    if not str(count).isdigit():
        raise ValueError("无法估计抽帧容量，未开始解码")
    count = int(count)
    if interval is None:
        return count
    try:
        duration = float(stream['duration'])
    except (ValueError, KeyError, TypeError):
        return count
    if not math.isfinite(duration) or duration < 0:
        return count
    return min(count, max(1, math.ceil(duration/interval)+1))
