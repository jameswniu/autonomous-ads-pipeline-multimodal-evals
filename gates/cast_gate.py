#!/usr/bin/env python3
"""cast_gate.py: is the person in a scene the presenter?

    cast_gate.py <reference image> <scene.mp4>             one verdict line for the scene
    cast_gate.py --reference <closer.mp4 | image> <out.jpg>  cut the presenter's reference

Every human on screen is the same presenter. A text prompt cannot hold a face. The Z.ai spot's
three scenes, shot from one board in August and again through the graph, show six different women
and none of them is the presenter, because each scene named only "a student" and the engine drew a
new one every time. So a scene that shows the presenter is rendered from her reference, and this
gate reads the result back before anything is built from it.

The face in each of FRAMES frames is the largest one insightface (buffalo_l) finds, and the verdict
is on the mean cosine similarity of those faces to the reference face. Every other face in the frame
is read too, since a stranger behind her is still a person on screen. One at least MIN_FACE of the
frame's height that falls under the floor in STRANGER_FRAMES frames or more fails the scene. The two
bounds keep a poster, a reflection or one glitched frame from reading as a person.

CAST_MIN is AUTHORED, from a measurement rather than a labelled pair (2026-09-24, against a single
reference still cut from the Z.ai closer). The six scene students averaged 0.16 at the most. Her
own closers from ten other spots averaged 0.44 at the least, and a scene rendered from her
reference averaged 0.46. The floor sits halfway across that gap.

Exit 0 PASS, 1 FAIL, 3 NOFACE when no sampled frame holds a face, 64 when the reference holds no
face or a file cannot be read. The machine line is always the last line printed.
"""
import os
import subprocess
import sys
import tempfile

CAST_MIN = 0.30
FRAMES = 8
MIN_FACE = 0.06          # a background face shorter than this share of the frame is too small to read
STRANGER_FRAMES = 2      # a background stranger has to be there in this many sampled frames
_APP = None


def verdict(sims, strangers=0):
    """PASS, FAIL or NOFACE for the similarities of a scene's main faces to the reference face,
    and the number of frames that held a second face that is not hers."""
    if not sims:
        return "NOFACE"
    if strangers >= STRANGER_FRAMES:
        return "FAIL"
    return "PASS" if sum(sims) / len(sims) >= CAST_MIN else "FAIL"


def line(sims, strangers=0):
    """The machine line pipeline/live.py reads, for a scene's similarities."""
    if not sims:
        return f"CAST_GATE faces=0 sim=nan min=nan strangers=0 floor={CAST_MIN:.2f} verdict=NOFACE"
    mean = sum(sims) / len(sims)
    return (f"CAST_GATE faces={len(sims)} sim={mean:.2f} min={min(sims):.2f} strangers={strangers} "
            f"floor={CAST_MIN:.2f} verdict={verdict(sims, strangers)}")


def app():
    global _APP
    if _APP is None:
        from insightface.app import FaceAnalysis   # the face extra, installed by make setup-face
        _APP = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])  # pii-allow: an onnxruntime provider name
        _APP.prepare(ctx_id=-1, det_size=(640, 640))
    return _APP


def score(frame_faces, ref):
    """The main face's similarity to the reference in each frame, and how many frames hold a
    second face, tall enough to read, that is not hers. frame_faces is (faces largest first,
    frame height) per frame, and ref is the reference face."""
    def sim(face):
        return float(sum(a * b for a, b in zip(face.normed_embedding, ref.normed_embedding, strict=True)))

    sims, strangers = [], 0
    for faces, height in frame_faces:
        if not faces:
            continue
        sims.append(sim(faces[0]))
        tall = [f for f in faces[1:] if (f.bbox[3] - f.bbox[1]) >= MIN_FACE * height]
        if any(sim(f) < CAST_MIN for f in tall):
            strangers += 1
    return sims, strangers


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
    """The presenter's reference: her most confidently detected face in the source, cropped square
    with room for hair and shoulders. A whole frame would hand the engine the closer's room too."""
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
    if len(argv) != 2:
        print(__doc__.split("\n\n")[1])
        return 64
    ref_path, scene = argv
    ref = largest(read_image(ref_path))
    if ref is None:
        print("CAST_GATE unreadable: the reference holds no face")
        return 64
    imgs = frames(scene)
    if not imgs:
        print("CAST_GATE unreadable: no frame could be read from the scene")
        return 64
    sims, strangers = score([(faces_in(img), img.shape[0]) for img in imgs], ref)
    print(line(sims, strangers))
    return {"PASS": 0, "FAIL": 1, "NOFACE": 3}[verdict(sims, strangers)]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
