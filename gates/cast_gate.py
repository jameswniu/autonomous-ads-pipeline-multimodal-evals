#!/usr/bin/env python3
"""cast_gate.py: is the person in a scene the story's character?

    cast_gate.py <reference image> <scene.mp4 | image> [--not <other reference>]   one verdict line
    cast_gate.py --reference <clip | image> <out.jpg>                             cut a reference

A story has one character, and she stays the same girl in every scene. She is never the narrator,
who appears only in the closer. A text prompt cannot hold a face. The Z.ai spot's three scenes,
shot from one board in August and again through the graph, named only "a student", so the engine
drew its own student each time and the girl changed between scenes. A scene that shows the
character is rendered from her reference, and this gate reads the result back before anything is
built from it.

The face in each of FRAMES frames is the largest one insightface (buffalo_l) finds, and the verdict
is on the mean cosine similarity of those faces to the reference face. A face shorter than MIN_FACE
of the frame's height is too small to read, a figure far off in a wide shot, so a frame whose
largest face is that small counts as holding none, and a scene with no readable face is NOFACE,
which goes to the eye, never a similarity reading off a few pixels. Every other face in the frame
is read too, since a stranger behind her is still a person on screen. One at least MIN_FACE of the
frame's height that falls under the floor in STRANGER_FRAMES frames or more fails the scene. The two
bounds keep a poster, a reflection or one glitched frame from reading as a person. With --not, the
main faces are also read against a second reference, the narrator's, and a scene that reads at least
as close to her as to the character fails, whatever the floor says.

CAST_MIN is AUTHORED, from measurements rather than a labelled pair. It was set on 2026-09-24, when
this gate held every scene to the narrator, halfway across a gap measured against an earlier crop of
her closer, where the six scene students averaged 0.16 at the most, her own closers from ten other
spots 0.44 at the least, and a scene rendered from her reference 0.46. Against the reference this
gate cuts from the same closer, the students read 0.12 at the most, her closers 0.42 at the least,
and two scenes rendered from it 0.42 and 0.53.

Read against the story's character, a reference cut from the August Z.ai scene a, the floor does
less. Her own scene reads 0.89, a visibly different girl 0.27 and the narrator's closer 0.15, and
both of those fail. The other students the engine drew from the same prompt read 0.50 to 0.66, and
the narrator rendered into one of her scenes 0.40, all above the floor. That narrator scene read
0.53 against the narrator's own reference, which is what --not catches. Her reference read against
the narrator's reads 0.12, which is how the two are held apart before a scene is paid for. Telling
two girls drawn from one prompt apart is beyond this gate, which is why every scene of hers is
rendered from her face and never left to a prompt, and why the eye sees the readings.

Exit 0 PASS, 1 FAIL, 3 NOFACE when no sampled frame holds a face, 64 when a reference holds no face
or a file cannot be read. The machine line is always the last line printed.
"""
import os
import subprocess
import sys
import tempfile

CAST_MIN = 0.30
FRAMES = 8
MIN_FACE = 0.06          # a face shorter than this share of the frame's height is too small to read
STRANGER_FRAMES = 2      # a background stranger has to be there in this many sampled frames
_APP = None


def verdict(sims, strangers=0, others=None):
    """PASS, FAIL or NOFACE for the similarities of a scene's main faces to the reference face, the
    number of frames that held a second face that is not hers, and, when a second reference was
    read, the main faces' similarities to it. A scene that reads at least as close to the second
    reference as to the first is the wrong person, however far over the floor it sits."""
    if not sims:
        return "NOFACE"
    if strangers >= STRANGER_FRAMES:
        return "FAIL"
    mean = sum(sims) / len(sims)
    if others and sum(others) / len(others) >= mean:
        return "FAIL"
    return "PASS" if mean >= CAST_MIN else "FAIL"


def line(sims, strangers=0, others=None):
    """The machine line pipeline/live.py reads, for a scene's similarities. `not` is the mean
    similarity to the second reference, - when none was read and nan when no face was found."""
    other = "-" if others is None else (f"{sum(others) / len(others):.2f}" if others else "nan")
    if not sims:
        return f"CAST_GATE faces=0 sim=nan min=nan strangers=0 not={other} floor={CAST_MIN:.2f} verdict=NOFACE"
    mean = sum(sims) / len(sims)
    return (f"CAST_GATE faces={len(sims)} sim={mean:.2f} min={min(sims):.2f} strangers={strangers} "
            f"not={other} floor={CAST_MIN:.2f} verdict={verdict(sims, strangers, others)}")


def app():
    global _APP
    if _APP is None:
        from insightface.app import FaceAnalysis   # the face extra, installed by make setup-face
        _APP = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])  # pii-allow: an onnxruntime provider name
        _APP.prepare(ctx_id=-1, det_size=(640, 640))
    return _APP


def _sim(face, ref):
    return float(sum(a * b for a, b in zip(face.normed_embedding, ref.normed_embedding, strict=True)))


def readable(faces, height):
    """The frame's main face, the largest, when it is tall enough to read, or None."""
    if faces and (faces[0].bbox[3] - faces[0].bbox[1]) >= MIN_FACE * height:
        return faces[0]
    return None


def score(frame_faces, ref):
    """The main face's similarity to the reference in each frame that holds a readable one, and how
    many frames hold a second face, tall enough to read, that is not hers. frame_faces is (faces
    largest first, frame height) per frame, and ref is the reference face."""
    sims, strangers = [], 0
    for faces, height in frame_faces:
        main = readable(faces, height)
        if main is None:
            continue
        sims.append(_sim(main, ref))
        tall = [f for f in faces[1:] if (f.bbox[3] - f.bbox[1]) >= MIN_FACE * height]
        if any(_sim(f, ref) < CAST_MIN for f in tall):
            strangers += 1
    return sims, strangers


def against(frame_faces, other):
    """The main face's similarity to a second reference, in each frame that holds a readable face."""
    mains = (readable(faces, height) for faces, height in frame_faces)
    return [_sim(main, other) for main in mains if main is not None]


def faces_in(img):
    """Every face in an image, largest first."""
    faces = app().get(img) if img is not None else []
    return sorted(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)


def largest(img):
    faces = faces_in(img)
    return faces[0] if faces else None


def frames(path, n=FRAMES):
    """n frames spread evenly through a clip, as images."""
    import cv2
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=60)
    try:
        dur = float(r.stdout.strip())
    except ValueError:
        return []
    out = []
    with tempfile.TemporaryDirectory() as d:
        for i in range(n):
            p = os.path.join(d, f"{i}.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * (i + 0.5) / n:.3f}", "-i", path,
                            "-frames:v", "1", p], capture_output=True, timeout=120)
            img = cv2.imread(p)
            if img is not None:
                out.append(img)
    return out


def read_image(path):
    import cv2
    return cv2.imread(path)


def is_video(path):
    return os.path.splitext(path)[1].lower() in (".mp4", ".mov", ".m4v", ".webm")


def cut_reference(src, out):
    """A reference face: the most confidently detected face in the source, cropped square with room
    for hair and shoulders. A whole frame would hand the engine the source's room too."""
    import cv2
    best = None
    for img in (frames(src) if is_video(src) else [read_image(src)]):
        f = largest(img)
        if f is not None and (best is None or f.det_score > best[1].det_score):
            best = (img, f)
    if best is None:
        print("CAST_REFERENCE none: no face in the source")
        return 64
    img, f = best
    x0, y0, x1, y1 = f.bbox
    h, w = img.shape[:2]
    side = min(2.6 * max(x1 - x0, y1 - y0), h, w)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + 0.35 * (y1 - y0)
    left, top = int(max(0, min(w - side, cx - side / 2))), int(max(0, min(h - side, cy - side / 2)))
    crop = cv2.resize(img[top:top + int(side), left:left + int(side)], (768, 768))
    cv2.imwrite(out, crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"CAST_REFERENCE face={f.det_score:.2f}")
    return 0


def main(argv):
    try:
        return run(argv)
    except ImportError as e:
        # Run with the repo's own interpreter instead of FACEPY, the face model is missing. That is
        # no reading, never a verdict.
        print(f"CAST_GATE unreadable: {e.name} is not installed here, run this with the face extra")
        return 64


def run(argv):
    if len(argv) == 3 and argv[0] == "--reference":
        return cut_reference(argv[1], argv[2])
    other_path = None
    if len(argv) == 4 and argv[2] == "--not":
        argv, other_path = argv[:2], argv[3]
    if len(argv) != 2:
        print(__doc__.split("\n\n")[1])
        return 64
    ref_path, scene = argv
    ref = largest(read_image(ref_path))
    if ref is None:
        print("CAST_GATE unreadable: the reference holds no face")
        return 64
    other = None
    if other_path is not None:
        other = largest(read_image(other_path))
        if other is None:
            print("CAST_GATE unreadable: the second reference holds no face")
            return 64
    # A still is read as one frame, which is how the character's reference is held apart from
    # the narrator's before any scene is paid for.
    imgs = frames(scene) if is_video(scene) else [img for img in [read_image(scene)] if img is not None]
    if not imgs:
        print("CAST_GATE unreadable: no frame could be read from the scene")
        return 64
    frame_faces = [(faces_in(img), img.shape[0]) for img in imgs]
    sims, strangers = score(frame_faces, ref)
    others = against(frame_faces, other) if other is not None else None
    print(line(sims, strangers, others))
    return {"PASS": 0, "FAIL": 1, "NOFACE": 3}[verdict(sims, strangers, others)]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
