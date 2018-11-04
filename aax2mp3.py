#!/usr/bin/env python
# vim: tabstop=4:softtabstop=4:shiftwidth=4:expandtab:
# -*- coding: utf-8 -*-

import os
import re
import argparse
from json import loads
import time

codecs = {  # codec, ext, container
    'mp3': ['libmp3lame', 'mp3', 'mp3'],
    #'aac': ['copy', 'm4a', 'm4a'],
    #'m4a': ['copy', 'm4a', 'm4a'],
    #'m4b': ['copy', 'm4a', 'm4b'],
    #'flac': ['flac', 'flac', 'flac'],
    #'opus': ['libopus', 'ogg', 'flac'],
}

def check_missing_authcode(args):
    '''ensure that an authcode is available'''
    if args.auth:
        return False

    tmp = os.environ.get('AUTHCODE', None)
    if tmp:
        args.auth = tmp
        return False

    for f in ['.authcode', '~/.authcode']:
        f = os.path.expanduser(f)
        if os.path.exists(f):
            with open(f) as fd:
                args.auth = fd.read().strip()
                return False
    print 'authcode not found in ".authcode", "~/.authcode", "$AUTHCODE", or the command line'
    return True

def missing_required_programs():
    '''ensure that various dependencies are available'''
    error = False
    required = ['ffmpeg', 'ffprobe', 'mp3splt']
    reqstr = ' '.join(required)
    found = None
    with os.popen('which {}'.format(reqstr)) as fd:
        found = fd.read() # .split()

    for p in required:
        if p not in found:
            error = True
            print 'missing dependency - {}'.format(p)
    return error

def numfix(n):
    '''convert the number of seconds into the format that mp3splt prefers'''
    n = float(n)
    m = int(n/60)
    s = n - (m*60)
    return "{}.{:.2f}".format(m,s)

def get_chapters(args, md):
    return [x['tags']['title'] for x in md]

def get_splitpoints(container, md):
    splitpoints = [float(x['start_time']) for x in md['chapters']]
    if container == 'mp3':
        splitpoints.append(md['chapters'][-1]['end_time']) # mp3splt needs to know the end of the split. it can't assume EOF
        splitpoints = [numfix(x) for x in splitpoints]

    return splitpoints

def probe_metadata(args, fn):
    if not os.path.exists(fn):
        print "Derp! Input file does not exist!"
        return None
    cmd = ['ffprobe', '-v', 'error', '-activation_bytes', args.auth, '-i', fn, '-of', 'json', '-show_chapters', '-show_programs', '-show_format',]

    fdi, fdo, fde = os.popen3(cmd)
    buf = fdo.read()
    fdo.close()
    fde.close()
    fdi.close()

    buf = re.sub('\s*[(](Una|A)bridged[)]', '', buf)  # I don't care about abridged or not
    buf = re.sub('\s+', ' ', buf)  # squish all whitespace runs

    ffprobe = loads(buf)
    return ffprobe

def split_file(args, destdir, src, md):
    '''Split the file into chapters'''
    splitpoints = get_splitpoints(args.container, md)
    t = md['format']['tags']
    if args.container == 'mp3':
        cmd = [
            'mp3splt', '-T', '12', '-o', '"Chapter @n"',
            '-g', u'''"r%[@N=1,@a={},@b={},@y={},@t=Chapter @n,@g=183]"'''.format(t['artist'], t['title'], t['date']),
            '-d', u'"{}"'.format(destdir),
            u'"{}"'.format(src),
            u' '.join(splitpoints)]
        if args.verbose or args.test:
            print cmd
            if args.test:
                return
        cmd = u' '.join(cmd)
        rv = os.system(cmd.encode('utf-8'))
        if rv == 0:
            os.unlink(src)
            pass
    else:
        raise RuntimeError("Don't know how to split {}".format(args.container))

def extract_image(args, destdir, fn):
    output = os.path.join(destdir, 'cover.jpg')
    cmd = ['ffmpeg', '-loglevel', 'error', '-stats', '-activation_bytes', args.auth, '-n', '-i', fn, '-an', '-codec:v', 'copy', u'{}'.format(output)]
    if os.path.exists(output) and args.overwrite:
        os.unlink(output)

    if args.test or args.verbose:
        print "extracting cover art"
        print u' '.join(cmd)
    if not args.test:
        x,y,z = os.popen3(cmd)
        x.close()
        y.read()
        z.read()
        y.close()
        z.close()
    return

def convert_file(args, fn, md):
    destdir = os.path.join(args.outdir, md['format']['tags']['artist'], md['format']['tags']['title'])
    if not os.path.exists(destdir):
        os.makedirs(destdir)

    extract_image(args, destdir, fn)

    if args.coverimage:
        return

    destfn = fn.replace('.aax', '.{}'.format(codecs[args.container][1]))
    output = os.path.join(destdir, destfn)
    if os.path.exists(output) and args.overwrite:
        print "removing transcoded file: {}".format(output)
        os.unlink(output)

    cmd = ['ffmpeg', '-loglevel', 'error', '-stats', '-activation_bytes', args.auth,
        '-n', '-i', fn, '-vn',
        '-codec:a', codecs[args.container][0], '-ab', md['format']['bit_rate'],
        '-map_metadata', '-1',
        '-metadata', u'title="{}"'.format(md['format']['tags']['title']),
        '-metadata', u'artist="{}"'.format(md['format']['tags']['artist']),
        '-metadata', u'album_artist="{}"'.format(md['format']['tags']['album_artist']),
        '-metadata', u'album="{}"'.format(md['format']['tags']['album']),
        '-metadata', u'date="{}"'.format(md['format']['tags']['date']),
        '-metadata', u'genre="{}"'.format(md['format']['tags']['genre']),
        '-metadata', u'copyright="{}"'.format(md['format']['tags']['copyright']),
        '-metadata', 'track="1/1"',
        u'"{}"'.format(output),
    ]
    cmd = u' '.join(cmd)
    if args.test or args.verbose:
        print cmd
        print "splitpoints:", get_splitpoints(args, md)
        if args.test:
            return split_file(args, destdir, output, md)

    t = time.time()
    os.system(cmd.encode('utf-8'))
    t = time.time() - t
    if args.verbose:
        print "transcoding time: {:0.2f}s".format(t)
    if args.single == True:
        return

    split_file(args, destdir, output, md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-a', '--authcode', default=None, dest='auth', help='Authorization Bytes')
    ap.add_argument('-f', '--format', default='mp3', choices=codecs.keys(), dest='container', help='output format. Default: %(default)s')
    ap.add_argument('-o', '--outputdir', default='Audiobooks', dest='outdir', help='output directory. Default: %(default)s')
    ap.add_argument('-c', '--clobber', default=False, dest='overwrite', action='store_true', help='overwrite existing files')
    ap.add_argument('-i', '--coverimage', default=False, dest='coverimage', action='store_true', help='only extract cover image')
    ap.add_argument('-s', '--single', default=False, dest='single', action='store_true', help="don't split into chapters")
    ap.add_argument('-t', '--test', default=False, dest='test', action='store_true', help='test input file(s)')
    ap.add_argument('-v', '--verbose', default=False, dest='verbose', action='store_true', help='extra verbose output')

    ap.add_argument(nargs='+', dest='input')
    args = ap.parse_args()

    something_is_wrong = False
    if check_missing_authcode(args):
        something_is_wrong = True

    if missing_required_programs():
        something_is_wrong = True

    if something_is_wrong:
        exit(1)

    for fn in args.input:
        md = probe_metadata(args, fn)
        convert_file(args, fn, md)

if __name__ == '__main__':
    main()
