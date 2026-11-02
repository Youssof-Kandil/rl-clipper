// Preview of the effect markers on the timeline canvas. Same timings and shapes as the
// export (backend media.effects_graph), drawn over the frame already on the canvas.
import { EFFECT_SECONDS, soundUrl, type EffectMarker, type SoundMarker } from "./api";

let scratch: HTMLCanvasElement | null = null;

const fade = (e: EffectMarker, t: number) => 1 - (t - e.t) / EFFECT_SECONDS[e.type];

/** Apply the effects active at source time ``t`` to what's on ``ctx``. */
export function drawEffects(ctx: CanvasRenderingContext2D, effects: EffectMarker[] | undefined, t: number) {
  const on = (effects ?? []).filter((e) => t >= e.t && t <= e.t + EFFECT_SECONDS[e.type]);
  if (!on.length) return;
  const { width: W, height: H } = ctx.canvas;
  scratch ??= document.createElement("canvas");
  if (scratch.width !== W || scratch.height !== H) {
    scratch.width = W;
    scratch.height = H;
  }
  const off = scratch.getContext("2d")!;
  off.drawImage(ctx.canvas, 0, 0);

  let zoom = 1;
  let dx = 0;
  let dy = 0;
  let shaking = false;
  for (const e of on) {
    const f = fade(e, t);
    if (e.type === "zoom") zoom += 0.18 * e.strength * Math.min((t - e.t) / 0.08, 1) * f;
    if (e.type === "shake" || e.type === "impact" || e.type === "glitch") {
      const amp = e.strength * (e.type === "glitch" ? 0.35 : 1) * f;
      dx += 0.03 * W * amp * Math.sin(t * 71);
      dy += 0.03 * H * amp * Math.cos(t * 53);
      shaking = true;
    }
  }
  const bw = on.some((e) => e.type === "bw");
  if (zoom !== 1 || shaking || bw) {
    const scale = zoom * (shaking ? 1 / 0.94 : 1);
    ctx.save();
    if (bw) ctx.filter = "grayscale(1)";
    ctx.translate(W / 2 - dx, H / 2 - dy);
    ctx.scale(scale, scale);
    ctx.drawImage(scratch, -W / 2, -H / 2);
    ctx.restore();
  }
  for (const e of on.filter((x) => x.type === "glitch")) {
    const q = (4 + 6 * e.strength) * (W / 1080) * 2;
    off.drawImage(ctx.canvas, 0, 0);
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.globalCompositeOperation = "screen";
    ctx.filter = "hue-rotate(140deg) saturate(2)";
    ctx.drawImage(scratch, q, -q / 2);
    ctx.restore();
  }
  const flash = on
    .filter((e) => e.type === "flash" || e.type === "impact")
    .reduce((a, e) => (t <= e.t + EFFECT_SECONDS.flash ? a + 0.6 * e.strength * (1 - (t - e.t) / EFFECT_SECONDS.flash) : a), 0);
  if (flash > 0) {
    ctx.save();
    ctx.globalAlpha = Math.min(flash, 1);
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, W, H);
    ctx.restore();
  }
}

/** Play one sound marker now (the preview; volumes over 100% play at 100%). */
export function playSound(m: Pick<SoundMarker, "sound" | "volume">) {
  const a = new Audio(soundUrl(m.sound));
  a.volume = Math.min(Math.max(m.volume, 0), 1);
  a.play().catch(() => {});
  return a;
}
