#!/usr/bin/env python
# vim: tabstop=4:softtabstop=4:shiftwidth=4:expandtab:
# -*- coding: utf-8 -*-

import os
from subprocess import check_output
import re
import argparse
from json import loads
from json import dump as jdump
import time
from unicodedata import normalize

try:
    import multiprocessing
except ImportError:
    multiprocessing = None

try:
    from setproctitle import setproctitle
except ImportError:

    def setproctitle(x):
        pass


args = None

codecs = {  # codec, ext, container
    "mp3": ["libmp3lame", "mp3", "mp3"],
    "aac": ["copy", "m4a", "m4a"],
    #'m4a': ['copy', 'm4a', 'm4a'],
    #'m4b': ['copy', 'm4a', 'm4b'],
    #'flac': ['flac', 'flac', 'flac'],
    #'opus': ['libopus', 'ogg', 'flac'],
}


def check_missing_authcode(args):
    """ensure that an authcode is available"""
    if args.auth:
        return False

    tmp = os.environ.get("AUTHCODE", None)
    if tmp:
        args.auth = tmp
        return False

    for f in [".authcode", "~/.authcode"]:
        f = os.path.expanduser(f)
        if os.path.exists(f):
            with open(f) as fd:
                args.auth = fd.read().strip()
                return False
    print('authcode not found in ".authcode", "~/.authcode", "$AUTHCODE", or the command line')
    return True


def missing_required_programs():
    """ensure that various dependencies are available"""
    error = False
    required = ["ffmpeg", "ffprobe", "mp3splt"]
    found = check_output(["which"] + required).decode("utf-8")

    for p in required:
        if p not in found:
            error = True
            print("missing dependency - {}".format(p))
    return error


def numfix(n):
    """convert the number of seconds into the format that mp3splt prefers"""
    n = float(n)
    m = int(n / 60)
    s = n - (m * 60)
    return "{}.{:.2f}".format(m, s)


def get_chapters(args, md):
    return [x["tags"]["title"] for x in md]


def get_splitpoints(container, md):
    """figure out where mp3splt should split the file"""
    splitpoints = [float(x["start_time"]) for x in md["chapters"]]
    if container == "mp3":
        splitpoints.append(
            md["chapters"][-1]["end_time"]
        )  # mp3splt needs to know the end of the split. it can't assume EOF
        splitpoints = [numfix(x) for x in splitpoints]

    return splitpoints


def probe_metadata(args, fn):
    """
    get file metadata, eg. chapters, titles, codecs. Recent version of ffprobe
    can emit json which is ever so helpful
    """
    if not os.path.exists(fn):
        print("Derp! Input file does not exist!")
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-activation_bytes",
        args.auth,
        "-i",
        fn,
        "-of",
        "json",
        "-show_chapters",
        "-show_programs",
        "-show_format",
    ]

    buf = check_output(cmd).decode("utf-8")

    buf = re.sub("\s*[(](Una|A)bridged[)]", "", buf)  # I don't care about abridged or not
    buf = re.sub("\s+", " ", buf)  # squish all whitespace runs

    ffprobe = loads(buf)
    return ffprobe


def split_file(args, destdir, src, md):
    """Split the file into chapters"""
    splitpoints = get_splitpoints(args.container, md)
    t = md["format"]["tags"]
    if args.container == "mp3":
        cmd = [
            "mp3splt",
            "-T",
            "12",
            "-o",
            '"Chapter @n"',
            "-g",
            '''"r%[@N=1,@a={},@b={},@y={},@t=Chapter @n,@g=183]"'''.format(t["artist"], t["title"], t["date"]),
            "-d",
            '"{}"'.format(destdir),
            '"{}"'.format(src),
            " ".join(splitpoints),
        ]
        if args.verbose or args.test:
            print(cmd)
            if args.test:
                return
        cmd = " ".join(cmd)
        rv = os.system(cmd.encode("utf-8"))
        if rv == 0:
            os.unlink(src)
            pass
    else:
        raise RuntimeError("Don't know how to split {}".format(args.container))


def extract_image(args, destdir, fn):
    output = os.path.join(destdir, "cover.jpg")
    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-stats",
        "-activation_bytes",
        args.auth,
        "-n",
        "-i",
        fn,
        "-an",
        "-codec:v",
        "copy",
        "{}".format(output),
    ]
    if os.path.exists(output) and args.overwrite:
        os.unlink(output)

    if args.test or args.verbose:
        print("extracting cover art")
        print(" ".join(cmd))
    if not args.test:
        buf = check_output(cmd)
    return


def sanitize(s):
    """replace any unsafe characters with underscores"""
    s = normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii", "ignore")
    s = s.replace("'", "").replace('"', "")
    # s = .encode('ascii', 'ignore')).replace("'", "").replace('"', '')
    # s = normalize("NFKD", s).encode('ascii', 'ignore')).replace("'", "").replace('"', '')
    s = re.sub("[^a-zA-Z0-9._/-]", "_", s)
    s = re.sub("_+", "_", s)
    return s


def convert_file(args, fn, md):
    destdir = None
    try:
        destdir = os.path.join(
            args.outdir, md["format"]["tags"]["artist"], md["format"]["tags"]["title"].replace("/", "-")
        )
    except KeyError:
        print("Metadata Error in {}".format(fn))
        return
    destdir = sanitize(destdir)

    if not os.path.exists(destdir):
        os.makedirs(destdir)

    # XXX figure out how to hook up decrypt-only, eg:
    # XXX ffmpeg -activation_bytes $AUTHCODE -i input.aax -c:a copy -vn -f mp4 output.mp4
    with open("{}/metadata.json".format(destdir), "w") as fd:
        jdump(md, fd, sort_keys=True, indent=4, separators=(",", ": "))

    if args.metadata:
        return

    try:
        extract_image(args, destdir, fn)
    except Exception:
        pass

    if args.coverimage:
        return

    if "Chapter " in str(os.listdir(destdir)):
        if args.verbose:
            print("Already processed {}".format(fn))
        return

    destfn = fn.replace(".aax", ".{}".format(codecs[args.container][1]))
    output = os.path.join(destdir, destfn)
    if os.path.exists(output) and args.overwrite:
        print("removing transcoded file: {}".format(output))
        os.unlink(output)

    ac = "2"
    ab = md["format"]["bit_rate"]
    if args.mono:
        ac = "1"
        ab = str(int(ab) / 2)

    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-stats",
        "-activation_bytes",
        args.auth,
        "-n",
        "-i",
        fn,
        "-vn",
        "-codec:a",
        codecs[args.container][0],
        "-ab",
        ab,
        "-ac",
        ac,
        "-map_metadata",
        "-1",
        "-metadata",
        'title="{}"'.format(md["format"]["tags"]["title"]),
        "-metadata",
        'artist="{}"'.format(md["format"]["tags"]["artist"]),
        "-metadata",
        'album_artist="{}"'.format(md["format"]["tags"]["album_artist"]),
        "-metadata",
        'album="{}"'.format(md["format"]["tags"]["album"]),
        "-metadata",
        'date="{}"'.format(md["format"]["tags"]["date"]),
        "-metadata",
        'genre="{}"'.format(md["format"]["tags"]["genre"]),
        "-metadata",
        'copyright="{}"'.format(md["format"]["tags"]["copyright"]),
        "-metadata",
        'track="1/1"',
        '"{}"'.format(output),
    ]
    cmd = " ".join(cmd)
    if args.test or args.verbose:
        print(cmd)
        print("splitpoints:", get_splitpoints(args, md))
        if args.test:
            return split_file(args, destdir, output, md)

    t = time.time()
    os.system(cmd.encode("utf-8"))
    t = time.time() - t
    if args.verbose:
        print("transcoding time: {:0.2f}s".format(t))
    if args.single == True:
        return

    split_file(args, destdir, output, md)


def process_wrapper(fn):
    global args
    setproctitle("transcode {}".format(fn))
    md = None
    try:
        md = probe_metadata(args, fn)
    except Exception as e:
        print(f"Caught exception {e} while probing metadata")

    try:
        convert_file(args, fn, md)
    except Exception as e:
        print(f"Caught exception {e} while probing metadata")


def main():
    global args
    ap = argparse.ArgumentParser()
    # arbitrary parameters
    ap.add_argument("-a", "--authcode", default=None, dest="auth", help="Authorization Bytes")
    ap.add_argument(
        "-f",
        "--format",
        default="mp3",
        choices=codecs.keys(),
        dest="container",
        help="output format. Default: %(default)s",
    )
    ap.add_argument(
        "-o", "--outputdir", default="Audiobooks", dest="outdir", help="output directory. Default: %(default)s"
    )
    ap.add_argument(
        "-p",
        "--processes",
        default=1,
        type=int,
        dest="processes",
        help="number of parallel transcoder processes to run. Default: %(default)d",
    )
    # binary flags
    ap.add_argument(
        "-c", "--clobber", default=False, dest="overwrite", action="store_true", help="overwrite existing files"
    )
    ap.add_argument("-d", "--decrypt", default=False, dest="decrypt", action="store_true", help="only decrypt files")
    ap.add_argument(
        "-i", "--coverimage", default=False, dest="coverimage", action="store_true", help="only extract cover image"
    )
    ap.add_argument("-m", "--mono", default=False, dest="mono", action="store_true", help="downmix to mono")
    ap.add_argument(
        "-s", "--single", default=False, dest="single", action="store_true", help="don't split into chapters"
    )
    ap.add_argument("-t", "--test", default=False, dest="test", action="store_true", help="test input file(s)")
    ap.add_argument("-v", "--verbose", default=False, dest="verbose", action="store_true", help="extra verbose output")
    ap.add_argument(
        "-x", "--extract-metadata", default=False, dest="metadata", action="store_true", help="only extract metadata"
    )

    ap.add_argument(nargs="+", dest="input")
    args = ap.parse_args()

    something_is_wrong = False
    if check_missing_authcode(args):
        something_is_wrong = True

    if missing_required_programs():
        something_is_wrong = True

    if something_is_wrong:
        exit(1)

    if args.mono:
        args.outdir += "-mono"

    if multiprocessing is None:
        args.processes = 1

    if args.processes < 2:
        for fn in args.input:
            process_wrapper(fn)
    else:
        proc_pool = multiprocessing.Pool(processes=args.processes, maxtasksperchild=1)
        setproctitle("transcode_dispatcher")
        proc_pool.map(process_wrapper, args.input, chunksize=1)

    os.system("stty echo")


if __name__ == "__main__":
    main()
