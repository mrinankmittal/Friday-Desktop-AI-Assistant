/*
 * The F.R.I.D.A.Y. orb.
 *
 * A HUD ring stack drawn around the existing green blob: rotating arcs, tick
 * marks, and two reactive waveform rings. Everything is driven by one scalar,
 * `energy`, which the voice states push around.
 *
 * The speaking waveform is synthesised, not sampled. Speech is played by SAPI
 * through the OS, so the browser has no access to the audio, and opening a
 * getUserMedia analyser here would fight the Python recogniser for the
 * microphone. The envelope below imitates syllable cadence instead.
 */
(function () {
    "use strict";

    var TAU = Math.PI * 2;

    var STATUS_TEXT = {
        idle: "Standing by",
        listening: "Listening",
        thinking: "Working on it",
        speaking: "Speaking",
    };

    // Where each state settles when nothing else is driving the orb.
    var RESTING_ENERGY = {
        idle: 0.1,
        listening: 0.36,
        thinking: 0.24,
        speaking: 0.6,
    };

    var SIZE = 640;
    var HALF = SIZE / 2;
    var WAVE_POINTS = 180;

    // Speaking decays back to idle on its own, so a dropped Python callback
    // cannot leave the orb talking forever.
    var SPEAKING_LEASE_MS = 20000;

    var canvas = null;
    var ctx = null;
    var hood = null;
    var statusEl = null;

    var state = "idle";
    var energy = RESTING_ENERGY.idle;
    var publishedEnergy = -1;
    var phase = [0, 0, 0, 0];
    var pulses = [];
    var lastPulseAt = 0;
    var speakingExpiresAt = 0;
    var lastFrameAt = 0;

    function clamp(value, low, high) {
        return value < low ? low : value > high ? high : value;
    }

    function randomPhase() {
        return Math.random() * TAU;
    }

    // A fresh cadence per utterance, so two replies never pulse identically.
    function reseed() {
        phase = [randomPhase(), randomPhase(), randomPhase(), randomPhase()];
    }

    /* Rough syllable envelope: fast oscillators for the syllables, one slow
     * gate that closes between words. */
    function speechEnvelope(t) {
        var syllables =
            0.55 * Math.sin(t * 12.5 + phase[0]) +
            0.28 * Math.sin(t * 20.3 + phase[1]) +
            0.17 * Math.sin(t * 31.7 + phase[2]);

        var gate = Math.pow(Math.max(0, Math.sin(t * 2.3 + phase[3])), 0.35);
        var level = 0.5 + 0.5 * syllables;

        return clamp(0.2 + 0.8 * level * (0.3 + 0.7 * gate), 0, 1);
    }

    function targetEnergy(t) {
        if (state === "speaking") {
            return 0.42 + 0.58 * speechEnvelope(t);
        }
        if (state === "listening") {
            // Breathing, plus a small tremor so it reads as "live".
            return (
                RESTING_ENERGY.listening +
                0.07 * Math.sin(t * 1.9 + phase[0]) +
                0.03 * Math.sin(t * 6.3 + phase[1])
            );
        }
        if (state === "thinking") {
            return RESTING_ENERGY.thinking + 0.05 * Math.sin(t * 5.5 + phase[2]);
        }
        return RESTING_ENERGY.idle + 0.04 * Math.sin(t * 1.1 + phase[3]);
    }

    function emitPulse(strength) {
        pulses.push({ radius: 150, alpha: clamp(strength, 0, 1) });
        if (pulses.length > 6) {
            pulses.shift();
        }
    }

    function setState(next, options) {
        var name = String(next || "idle").toLowerCase();
        if (!STATUS_TEXT[name]) {
            name = "idle";
        }

        var changed = name !== state;
        state = name;

        if (name === "speaking") {
            speakingExpiresAt = performance.now() + SPEAKING_LEASE_MS;
        } else {
            speakingExpiresAt = 0;
        }

        if (changed) {
            reseed();
            emitPulse(name === "idle" ? 0.35 : 0.85);
        }

        if (hood) {
            hood.dataset.state = name;
        }
        if (document.body) {
            document.body.dataset.orb = name;
        }
        if (statusEl) {
            var label = (options && options.status) || STATUS_TEXT[name];
            statusEl.textContent = label;
        }
    }

    function resize() {
        if (!canvas) {
            return;
        }
        var ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = SIZE * ratio;
        canvas.height = SIZE * ratio;
        ctx = canvas.getContext("2d");
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    function glow(color, blur) {
        ctx.shadowColor = color;
        ctx.shadowBlur = blur;
    }

    function clearGlow() {
        ctx.shadowBlur = 0;
    }

    function drawAmbient(t) {
        var reach = 300 * (0.55 + 0.45 * energy);
        var gradient = ctx.createRadialGradient(0, 0, 40, 0, 0, reach);
        gradient.addColorStop(0, "rgba(0, 255, 120, " + (0.16 + 0.22 * energy) + ")");
        gradient.addColorStop(0.45, "rgba(0, 200, 90, " + (0.05 + 0.09 * energy) + ")");
        gradient.addColorStop(1, "rgba(0, 60, 25, 0)");
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(0, 0, reach, 0, TAU);
        ctx.fill();
    }

    /* The reactive ring. Radius is a base circle plus three angular harmonics,
     * scaled by energy, so it ripples like a spoken waveform wrapped on itself. */
    function drawWave(radius, amplitude, width, alpha, t, direction) {
        ctx.beginPath();
        for (var i = 0; i <= WAVE_POINTS; i++) {
            var angle = (i / WAVE_POINTS) * TAU;
            var offset =
                amplitude *
                (0.5 * Math.sin(angle * 3 + direction * t * 2.2 + phase[0]) +
                    0.3 * Math.sin(angle * 7 - direction * t * 3.1 + phase[1]) +
                    0.2 * Math.sin(angle * 13 + direction * t * 4.7 + phase[2]));

            var r = radius + offset;
            var x = Math.cos(angle) * r;
            var y = Math.sin(angle) * r;
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }
        ctx.closePath();
        ctx.strokeStyle = "rgba(0, 255, 120, " + alpha + ")";
        ctx.lineWidth = width;
        glow("rgba(0, 255, 110, 0.9)", 14 + 26 * energy);
        ctx.stroke();
        clearGlow();
    }

    function drawArc(radius, from, span, width, alpha) {
        ctx.beginPath();
        ctx.arc(0, 0, radius, from, from + span);
        ctx.strokeStyle = "rgba(120, 255, 170, " + alpha + ")";
        ctx.lineWidth = width;
        ctx.lineCap = "round";
        glow("rgba(0, 255, 110, 0.8)", 10 + 14 * energy);
        ctx.stroke();
        clearGlow();
    }

    function drawTicks(radius, count, length, t, alpha) {
        ctx.save();
        ctx.rotate(t * 0.12);
        ctx.strokeStyle = "rgba(0, 255, 110, " + alpha + ")";
        ctx.lineWidth = 1.4;
        for (var i = 0; i < count; i++) {
            var angle = (i / count) * TAU;
            var long = i % 5 === 0;
            var inner = radius;
            var outer = radius + (long ? length * 1.9 : length);
            ctx.beginPath();
            ctx.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
            ctx.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
            ctx.stroke();
        }
        ctx.restore();
    }

    /* A bright head sweeping the outer ring, like a radar trace. */
    function drawSweep(radius, t, alpha) {
        var head = (t * 0.9) % TAU;
        var steps = 26;
        ctx.lineCap = "round";
        for (var i = 0; i < steps; i++) {
            var tail = head - (i / steps) * 1.15;
            var fade = (1 - i / steps) * alpha;
            ctx.beginPath();
            ctx.arc(0, 0, radius, tail - 0.05, tail);
            ctx.strokeStyle = "rgba(190, 255, 215, " + fade + ")";
            ctx.lineWidth = 2.6;
            ctx.stroke();
        }
    }

    function drawPulses(delta) {
        for (var i = pulses.length - 1; i >= 0; i--) {
            var pulse = pulses[i];
            pulse.radius += delta * 150;
            pulse.alpha -= delta * 0.85;
            if (pulse.alpha <= 0 || pulse.radius > 315) {
                pulses.splice(i, 1);
                continue;
            }
            ctx.beginPath();
            ctx.arc(0, 0, pulse.radius, 0, TAU);
            ctx.strokeStyle = "rgba(140, 255, 190, " + pulse.alpha * 0.5 + ")";
            ctx.lineWidth = 2;
            ctx.stroke();
        }
    }

    function drawCore(t) {
        var radius = 150 + 26 * energy;
        var gradient = ctx.createRadialGradient(0, 0, 8, 0, 0, radius);
        gradient.addColorStop(0, "rgba(220, 255, 235, " + (0.32 + 0.4 * energy) + ")");
        gradient.addColorStop(0.35, "rgba(0, 255, 130, " + (0.14 + 0.2 * energy) + ")");
        gradient.addColorStop(1, "rgba(0, 120, 50, 0)");
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, TAU);
        ctx.fill();
    }

    function frame(now) {
        window.requestAnimationFrame(frame);

        if (!ctx || document.hidden) {
            lastFrameAt = now;
            return;
        }

        var delta = lastFrameAt ? Math.min((now - lastFrameAt) / 1000, 0.05) : 0.016;
        lastFrameAt = now;

        var t = now / 1000;

        if (state === "speaking" && speakingExpiresAt && now > speakingExpiresAt) {
            setState("idle");
        }

        // Chase the target so state changes ease in instead of snapping.
        var chase = state === "speaking" ? 0.35 : 0.12;
        energy += (targetEnergy(t) - energy) * chase;
        energy = clamp(energy, 0, 1);

        if (state === "listening" && now - lastPulseAt > 1500) {
            lastPulseAt = now;
            emitPulse(0.5);
        }

        ctx.clearRect(0, 0, SIZE, SIZE);
        ctx.save();
        ctx.translate(HALF, HALF);

        drawAmbient(t);
        drawCore(t);
        drawPulses(delta);

        var amplitude = 6 + 40 * energy;
        drawWave(215, amplitude, 2.6, 0.42 + 0.5 * energy, t, 1);
        drawWave(198, amplitude * 0.6, 1.6, 0.2 + 0.35 * energy, t, -1);

        var spin = t * 0.35;
        drawArc(245, spin, 1.5, 2.4, 0.3 + 0.4 * energy);
        drawArc(245, spin + Math.PI, 0.9, 2.4, 0.25 + 0.35 * energy);
        drawArc(263, -spin * 1.4, 2.2, 1.6, 0.2 + 0.3 * energy);
        drawArc(263, -spin * 1.4 + Math.PI * 1.2, 0.5, 1.6, 0.2 + 0.3 * energy);

        drawTicks(278, 60, 5, t, 0.16 + 0.34 * energy);

        ctx.beginPath();
        ctx.arc(0, 0, 296, 0, TAU);
        ctx.strokeStyle = "rgba(0, 255, 110, " + (0.1 + 0.2 * energy) + ")";
        ctx.lineWidth = 1.2;
        ctx.stroke();

        drawSweep(296, t, 0.25 + 0.5 * energy);

        ctx.restore();

        // Let CSS light the blob from the same signal, but only on real change.
        if (hood && Math.abs(energy - publishedEnergy) > 0.01) {
            publishedEnergy = energy;
            hood.style.setProperty("--orb-energy", energy.toFixed(3));
        }
    }

    function init() {
        canvas = document.getElementById("orb-canvas");
        hood = document.getElementById("FridayHood");
        statusEl = document.getElementById("orb-status");

        if (!canvas || !canvas.getContext) {
            console.error("The orb canvas is missing; voice states will not animate.");
            return;
        }

        resize();
        reseed();
        setState("idle");
        window.addEventListener("resize", resize);
        window.requestAnimationFrame(frame);
    }

    window.FridayOrb = {
        setState: setState,
        getState: function () {
            return state;
        },
        reseed: reseed,
        pulse: emitPulse,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
