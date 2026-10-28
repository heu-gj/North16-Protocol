"""Initialize, extract, annotate and export an independent annotation workspace."""
import argparse
import json

from .workspace import AnnotationWorkspace


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="action",required=True)
    init=sub.add_parser("initialize",help="Create a new annotation workspace without decoding")
    source=init.add_mutually_exclusive_group(required=True)
    source.add_argument("--raw");source.add_argument("--dataset")
    init.add_argument("--output",required=True);init.add_argument("--segments",nargs="+")
    extract=sub.add_parser("extract",help="Extract videos inside the annotation workspace")
    export=sub.add_parser("export",help="Export images + masks + metadata as one delivery package")
    gui=sub.add_parser("gui",help="Open annotation GUI, saving JSON next to workspace images")
    for action in (extract,export,gui):action.add_argument("--root",required=True)
    for action in (extract,export):
        action.add_argument("--sequences",nargs="+");action.add_argument("--sensor",choices=("visible","infrared"))
        action.add_argument("--cameras",nargs="+")
    extract.add_argument("--interval",type=float);extract.add_argument("--dry-run",action="store_true")
    extract.add_argument("--no-progress",action="store_true",help="Disable stderr extraction progress")
    extract.add_argument("--ffmpeg",default="ffmpeg");extract.add_argument("--ffprobe",default="ffprobe")
    export.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    if args.action=="initialize":
        if args.dataset and args.segments:parser.error("--segments only applies to --raw")
        report=AnnotationWorkspace.initialize(args.output,raw=args.raw,dataset=args.dataset,segments=args.segments)
    else:
        workspace=AnnotationWorkspace(args.root)
        if args.action=="gui":
            from north16.gui.app import main as gui_main
            return gui_main(["--dataset",str(workspace.root)])
        selection=dict(sequences=args.sequences,sensor=args.sensor,cameras=args.cameras)
        if args.action=="extract":
            from north16.camera.progress import ExtractionProgress
            report=workspace.extract(**selection,interval=args.interval,dry_run=args.dry_run,ffmpeg=args.ffmpeg,ffprobe=args.ffprobe,
                                     progress=None if args.no_progress or args.dry_run else ExtractionProgress())
        else:report=workspace.export(args.output,**selection)
    print(json.dumps(report,ensure_ascii=False,indent=2))
