/** Canvas stand-in for the ffmpeg export (media.vertical_filter + captions.write_ass),
 * so the timeline preview looks like the file you'll get. */
import type { Cue, VerticalStyle } from "./api";

export interface Look {
  vertical: boolean;
  style: VerticalStyle;
  cropX: number;
  zoom: number;
  blur: number; // sigma at 1080 wide
  sharp: number; // oval style: share of the height kept sharp
}

export interface CaptionLook {
  size: number; // px at 1080 wide
  position: "upper" | "middle" | "lower";
  upper: boolean;
  highlight: boolean;
  color: string; // the word being said
}

// Same fractions as captions._POSITIONS.
const CAPTION_Y = {
  vertical: { upper: 0.27, middle: 0.5, lower: 0.7 },
  wide: { upper: 0.18, middle: 0.5, lower: 0.84 },
};

let scratch: HTMLCanvasElement | null = null;

/** A ``aspect`` (w/h) window of the source, full height unless zoomed, centred on cropX. */
function windowOf(vw: number, vh: number, cropX: number, zoom: number, aspect: number) {
  const h = vh / Math.min(Math.max(zoom, 1), 2);
  const w = Math.min(h * aspect, vw);
  const x = Math.min(Math.max(cropX * vw - w / 2, 0), vw - w);
  return { x, y: (vh - h) / 2, w, h };
}

export function drawFrame(ctx: CanvasRenderingContext2D, video: HTMLVideoElement, look: Look) {
  const { width: W, height: H } = ctx.canvas;
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);
  if (!vw || !vh) return;
  if (!look.vertical) {
    ctx.drawImage(video, 0, 0, vw, vh, 0, 0, W, H);
    return;
  }
  const blurPx = (look.blur * W) / 1080;
  const tall = windowOf(vw, vh, look.cropX, look.zoom, 9 / 16);
  const drawTall = () => ctx.drawImage(video, tall.x, tall.y, tall.w, tall.h, 0, 0, W, H);

  if (look.style === "crop") {
    drawTall();
    return;
  }
  if (look.style === "fit") {
    const bg = windowOf(vw, vh, 0.5, 1, 9 / 16);
    ctx.filter = `blur(${blurPx}px) brightness(0.92)`;
    ctx.drawImage(video, bg.x, bg.y, bg.w, bg.h, 0, 0, W, H);
    ctx.filter = "none";
    const fh = (W * vh) / vw;
    ctx.drawImage(video, 0, 0, vw, vh, 0, (H - fh) / 2, W, fh);
    return;
  }
  if (look.style === "focus45") {
    ctx.filter = `blur(${blurPx}px) brightness(0.9)`;
    drawTall();
    ctx.filter = "none";
    const f = windowOf(vw, vh, look.cropX, look.zoom, 4 / 5);
    ctx.drawImage(video, f.x, f.y, f.w, f.h, 0, (H * 285) / 1920, W, (H * 1350) / 1920);
    return;
  }
  // Oval focus: blurred tall crop, then the sharp one faded out through an oval.
  ctx.filter = `blur(${blurPx}px)`;
  drawTall();
  ctx.filter = "none";
  scratch ??= document.createElement("canvas");
  scratch.width = W;
  scratch.height = H;
  const s = scratch.getContext("2d")!;
  s.globalCompositeOperation = "source-over";
  s.drawImage(video, tall.x, tall.y, tall.w, tall.h, 0, 0, W, H);
  s.globalCompositeOperation = "destination-in";
  const rx = W * 0.62;
  const ry = (H * Math.max(look.sharp, 0.1)) / 2;
  s.setTransform(rx / ry, 0, 0, 1, W / 2, H / 2);
  const g = s.createRadialGradient(0, 0, 0, 0, 0, ry * 1.45);
  g.addColorStop(0, "rgba(0,0,0,1)");
  g.addColorStop(1 / 1.45, "rgba(0,0,0,1)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  s.fillStyle = g;
  s.fillRect(-W, -H, W * 4, H * 2);
  s.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(scratch, 0, 0);
}

/** The cue's word timings: as transcribed while the text is unchanged, otherwise
 * spread evenly over the cue (same rule as captions.cue_words). */
export function cueWords(cue: Cue): { start: number; end: number; text: string }[] {
  const tokens = cue.text.split(/\s+/).filter(Boolean);
  const words = cue.words ?? [];
  if (words.length === tokens.length && words.every((w, i) => w.text === tokens[i])) return words;
  const step = (cue.end - cue.start) / Math.max(tokens.length, 1);
  return tokens.map((text, i) => ({ start: cue.start + i * step, end: cue.start + (i + 1) * step, text }));
}

/** Index of the word being said at ``t`` (stays lit until the next word), -1 before the first. */
export function activeWord(cue: Cue, t: number): number {
  const words = cueWords(cue);
  let idx = -1;
  words.forEach((w, i) => {
    if (w.start <= t) idx = i;
  });
  return idx;
}

export function drawCaption(ctx: CanvasRenderingContext2D, text: string, look: CaptionLook, lit = -1) {
  const { width: W, height: H } = ctx.canvas;
  const scale = W / (H > W ? 1080 : 1920);
  const size = look.size * scale;
  const outline = Math.max(Math.round(look.size / 12), 3) * scale;
  const words = text.split(/\s+/).filter(Boolean).map((w) => (look.upper ? w.toUpperCase() : w));
  ctx.font = `900 ${size}px "Arial Black", "Arial", sans-serif`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.lineJoin = "round";
  const space = ctx.measureText(" ").width;
  // Wrap like libass's smart wrapping: as few lines as fit inside the 60 px side
  // margins, then as even as possible (narrowest width that still needs no extra line).
  const widths = words.map((w) => ctx.measureText(w).width);
  const wrap = (limit: number) => {
    const out: number[][] = [];
    let lineW = 0;
    widths.forEach((ww, i) => {
      const cur = out[out.length - 1];
      if (cur && lineW + space + ww <= limit) {
        cur.push(i);
        lineW += space + ww;
      } else {
        out.push([i]);
        lineW = ww;
      }
    });
    return out;
  };
  const maxW = W - 120 * scale;
  let lines = wrap(maxW);
  if (lines.length > 1) {
    let lo = Math.max(...widths);
    let hi = maxW;
    for (let k = 0; k < 20; k++) {
      const mid = (lo + hi) / 2;
      if (wrap(mid).length <= lines.length) hi = mid;
      else lo = mid;
    }
    lines = wrap(hi);
  }
  const lineH = size * 1.15;
  const y0 = H * CAPTION_Y[H > W ? "vertical" : "wide"][look.position] - ((lines.length - 1) * lineH) / 2;
  lines.forEach((line, li) => {
    const y = y0 + li * lineH;
    const lineWidths = line.map((i) => widths[i]);
    let x = W / 2 - (lineWidths.reduce((a, b) => a + b, 0) + space * (line.length - 1)) / 2;
    // Outline every word first so no stroke covers a neighbour's fill.
    const xs = lineWidths.map((w) => {
      const at = x;
      x += w + space;
      return at;
    });
    ctx.shadowColor = "rgba(0,0,0,0.6)";
    ctx.shadowOffsetX = ctx.shadowOffsetY = Math.max(outline / 2, 2);
    ctx.lineWidth = outline * 2;
    ctx.strokeStyle = "#000";
    line.forEach((i, k) => ctx.strokeText(words[i], xs[k], y));
    ctx.shadowColor = "transparent";
    line.forEach((i, k) => {
      ctx.fillStyle = look.highlight && i === lit ? look.color : "#fff";
      ctx.fillText(words[i], xs[k], y);
    });
  });
}
