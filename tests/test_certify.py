"""The certificate is an instrument that measures instruments, so it needs its own checks.

Three of its own defects turned up while it was being built, each of which made an honest probe
look blind: a periodic reference clip whose correlation peak repeated every 435 ms, motion that
was the derivative of the envelope rather than the envelope, and ffmpeg silently capping a
positive audio delay at about 75 ms so three different doses arrived identical. The last one is
what verify_dose exists to catch, and it is tested here.
"""
import os
import sys
import tempfile

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))
import certify  # noqa: E402


def test_fit_recovers_a_known_line():
    doses = [-160, -80, 0, 80, 160]
    slope, intercept, sigma = certify.fit(doses, [-d * 1.0 + 5 for d in doses])
    assert slope == pytest.approx(-1.0, abs=1e-6)
    assert intercept == pytest.approx(5.0, abs=1e-6)
    assert sigma == pytest.approx(0.0, abs=1e-6)


def test_fit_reports_the_scatter_it_finds():
    doses = [-160, -80, 0, 80, 160]
    clean = certify.fit(doses, [-d for d in doses])[2]
    noisy = certify.fit(doses, [-d + n for d, n in zip(doses, [60, -55, 40, -70, 50], strict=True)])[2]
    assert clean < 1.0 < noisy, f"scatter not reported: clean {clean}, noisy {noisy}"


@pytest.mark.parametrize("slope,sigma,expect,ok", [
    (1.00, 2.0, +1, True),
    (-1.00, 2.0, -1, True),
    (1.00, 2.0, -1, False),      # a silent sign inversion is the defect that shipped a desync
    (0.20, 2.0, +1, False),      # reads a shift as a fifth of itself
    (1.00, 200.0, +1, False),    # cannot resolve the 80 ms the labelled edges are apart
])
def test_a_probe_that_stopped_tracking_does_not_certify(slope, sigma, expect, ok):
    assert certify.tracks(slope, sigma, expect) is ok


def test_verify_dose_refuses_a_clip_that_did_not_get_its_dose():
    """ffmpeg's -itsoffset capped a positive delay at about 75 ms, so doses of 80, 120 and 160
    all arrived as 75 and the probes read the same number three times. The harness now checks
    what landed rather than what it asked for."""
    with tempfile.TemporaryDirectory() as tmp:
        vid, wav = certify.build(tmp)
        honest = certify.dosed(vid, wav, 120, os.path.join(tmp, "honest.mp4"))
        assert certify.verify_dose(honest, wav, 120) is not None, "a correct dose was rejected"
        # The same clip, asked to answer for a dose it does not carry.
        assert certify.verify_dose(honest, wav, -40) is None, "a wrong dose passed verification"


def test_the_reference_clip_is_aperiodic():
    """A periodic stimulus gives the correlation an identical peak every period, and the argmax
    then jumps between aliases. The first reference clip modulated a sine at 2.3 Hz and produced
    readings of -600, -536 and +48 ms for doses 80 ms apart."""
    env = np.array([certify.envelope_at(i / 100.0) for i in range(certify.SECONDS * 100)])
    env = env - env.mean()
    # Autocorrelation must not come back near its own peak at any non-zero lag inside the search.
    peak = float((env * env).sum())
    worst = max(float((env[:-k] * env[k:]).sum()) / peak for k in range(20, 200))
    assert worst < 0.6, f"the reference envelope repeats itself at {worst:.2f} of its own peak"


def test_a_dose_that_never_read_fails_the_whole_certificate(monkeypatch):
    """Skipping unreadable doses and fitting the survivors is how a probe blind on one whole side
    certifies as tracking. Every dose has to read."""
    seen = {}

    def half_blind(probe, clip):
        ms = int(clip.rsplit("-", 1)[1].split(".")[0])
        seen[ms] = True
        return None if ms > 0 else -ms

    monkeypatch.setattr(certify, "read", half_blind)
    with tempfile.TemporaryDirectory() as tmp:
        vid, wav = certify.build(tmp)
        c = certify.certify("sync_probe", vid, wav, tmp)
    assert c["verdict"] == "INCOMPLETE", c
    assert c["skipped_ms"], "the unread doses were not reported"
