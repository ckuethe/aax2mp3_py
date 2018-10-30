# AAX2MP3_py


This is a rough rewrite of [KrumpetPirate AAXtoMP3](https://github.com/KrumpetPirate/AAXtoMP3) but in python. As with `AAXtoMP3` you will need to use a tool like [audible-activator](https://github.com/inAudible-NG/audible-activator) to get the authcode needed to decrypt the audio.

An advantage this script has over the original is that it uses [mp3splt](https://github.com/search?l=C&q=mp3splt&type=Repositories) to split the decrypted audio into chapter files which is much faster than using `ffmpeg`. A disadvantage this script has compared to the original is that it only supports `MP3` output (for now)

### Usage

```
usage: aax2mp3.py [-h] [-a AUTH] [-f {mp3}] [-o OUTDIR] [-c] [-s] [-t] [-v]
                  input [input ...]

positional arguments:
  input

optional arguments:
  -h, --help            show this help message and exit
  -a AUTH, --authcode AUTH
                        Authorization Bytes
  -f {mp3}, --format {mp3}
                        output format. Default: mp3
  -o OUTDIR, --outputdir OUTDIR
                        output directory. Default: Audiobooks
  -c, --clobber         overwrite existing files
  -s, --single          don't split into chapters
  -t, --test            test input file(s)
  -v, --verbose         extra verbose output
```

### To Do

- support more audio formats
- fix metadata (id3) generation
