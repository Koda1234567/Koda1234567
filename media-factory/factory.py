#!/usr/bin/env python3
"""Media Factory MVP. Safe: no publishing, no paid APIs, no avatar cloning."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
PLATFORMS = ("youtube", "tiktok", "vk", "instagram")
LOG = logging.getLogger("media_factory")


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    hook: str
    facts: tuple[dict[str, str], ...]
    takeaway: str
    sources: tuple[str, ...]


class TopicScoutAgent:
    """Load source-grounded topics; later add authorized vidIQ research input."""

    def discover(self, file: Path) -> Topic:
        doc = json.loads(file.read_text(encoding="utf-8"))
        for field in ("slug", "title", "hook", "facts", "takeaway", "sources"):
            if not doc.get(field):
                raise ValueError("Missing required field: " + field)
        return Topic(
            doc["slug"], doc["title"], doc["hook"],
            tuple(doc["facts"]), doc["takeaway"], tuple(doc["sources"])
        )


class FactCheckAgent:
    """Reject uncited assertions. This is not a substitute for human review."""

    def check(self, topic: Topic) -> None:
        if len(set(topic.sources)) < 2:
            raise ValueError("At least two independent source URLs are required")
        for fact in topic.facts:
            if not fact.get("text") or not fact.get("source"):
                raise ValueError("Every fact needs text and source")
            if fact["source"] not in topic.sources:
                raise ValueError("Unknown source URL for fact")
            if not fact["source"].startswith("https://"):
                raise ValueError("HTTPS source URLs only")
        if len(topic.facts) < 2:
            raise ValueError("Need at least two sourced facts")


class ScriptwriterAgent:
    """Draft a 15-second, four-card story without inventing new facts."""

    def draft(self, topic: Topic) -> list[dict[str, Any]]:
        titles = ["ЗА 15 СЕКУНД", "1997–1998", "2007", "ГЛАВНЫЙ УРОК"]
        copy = [topic.hook] + [f["text"] for f in topic.facts[:2]] + [topic.takeaway]
        return [{"label": label, "text": text, "seconds": 3.75}
                for label, text in zip(titles, copy)]


class QualityGateAgent:
    """A draft is never approved to publish by software alone."""

    def review(self, topic: Topic, slides: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "source_count": len(topic.sources),
            "claims_count": len(topic.facts),
            "long_cards": [i for i, s in enumerate(slides, 1) if len(s["text"]) > 130],
            "approved_to_publish": False,
            "needs_fact_review": True,
            "talking_avatar_generated": False,
            "voiceover_included": False
        }


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    raise RuntimeError("Install a font with Russian/Cyrillic support")


def _wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        test = (current + " " + word).strip()
        if current and draw.textbbox((0, 0), test, font=f)[2] > width:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


class RenderAgent:
    """Use FFmpeg to produce a vertical technical preview, NOT talking head."""

    def card(self, slide: dict[str, Any], out: Path, portrait: Path | None) -> None:
        w, h = 720, 1280
        im = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(im)
        for y in range(h):
            mix = y / h
            draw.line((0, y, w, y),
                      fill=(int(12 + mix * 9), int(10 + mix * 6), int(24 + mix * 20)))
        for radius in (195, 250, 315):
            draw.ellipse((560-radius, 175-radius, 560+radius, 175+radius),
                         outline="#342346", width=2)
        draw.rounded_rectangle((42, 46, 390, 101), radius=25, fill="#251637")
        draw.text((67, 57), "ИСТОРИИ БОЛЬШИХ ДЕНЕГ",
                  font=_font(20, True), fill="#D9BAFF")
        draw.text((46, 165), slide["label"], font=_font(24, True), fill="#B894FF")
        f = _font(53, True)
        for i, line in enumerate(_wrap(draw, slide["text"], f, 630)):
            draw.text((45, 266 + i * 78), line, font=f, fill="#F8F7FF")
        if portrait and portrait.is_file():
            subject = Image.open(portrait).convert("RGB")
            side = min(subject.size)
            left = (subject.width - side) // 2
            subject = subject.crop((left, 0, left + side, side)).resize((210, 210))
            mask = Image.new("L", (210, 210), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 210, 210), fill=255)
            im.paste(subject, (46, 973), mask)
            draw.text((290, 1040), "ВЕДУЩИЙ", font=_font(22, True), fill="#C5A5FF")
            draw.text((290, 1080), "Демо: статичный портрет",
                      font=_font(17), fill="#C7C3CF")
        else:
            draw.text((46, 1094), "Истории бизнеса без воды",
                      font=_font(24), fill="#C7C3CF")
        draw.text((45, 1224), "ПИЛОТ / СУБТИТРЫ / БЕЗ ГОЛОСА",
                  font=_font(16), fill="#B4A8CB")
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out)

    def video(self, slides: list[dict[str, Any]], cards: Path,
              path: Path, portrait: Path | None = None) -> bool:
        cards.mkdir(parents=True, exist_ok=True)
        for index, slide in enumerate(slides):
            self.card(slide, cards / f"card_{index:02d}.png", portrait)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            LOG.warning("FFmpeg not found; PNG cards were generated")
            return False
        concat = cards / "frames.ffconcat"
        records = ["ffconcat version 1.0"]
        for index, slide in enumerate(slides):
            records.extend((f"file 'card_{index:02d}.png'",
                            f"duration {float(slide['seconds']):.3f}"))
        records.extend((f"file 'card_{len(slides) - 1:02d}.png'", "duration 0.041667"))
        concat.write_text("\n".join(records) + "\n", encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-safe", "0", "-f", "concat", "-i", str(concat),
             "-vf", "fps=24,format=yuv420p", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "24",
             "-movflags", "+faststart",
             "-t", str(sum(float(s["seconds"]) for s in slides)), str(path)],
            check=True, timeout=180
        )
        return True


class DistributionAgent:
    """Generate platform-specific drafts, never schedule/publish automatically."""

    HASHTAGS = {
        "youtube": ["#shorts", "#бизнес", "#историикомпаний", "#деньги"],
        "tiktok": ["#бизнес", "#истории", "#факты", "#деньги"],
        "vk": ["#бизнес", "#деньги", "#интересныефакты", "#истории"],
        "instagram": ["#reels", "#бизнес", "#историибрендов", "#деньги"]
    }

    def export(self, topic: Topic, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        for platform in PLATFORMS:
            post = {
                "platform": platform, "title": topic.hook[:95],
                "description": topic.title + ". " + topic.takeaway
                               + "\n\nИсточники: " + " ".join(topic.sources),
                "hashtags": self.HASHTAGS[platform],
                "media_file": "../preview.mp4",
                "publish": False, "needs_approval": True
            }
            (folder / f"{platform}.json").write_text(
                json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8"
            )


class AnalyticsAgent:
    """Rank real metrics exported by user; never invent audience data."""

    def report(self, csv_file: Path) -> dict[str, Any]:
        with csv_file.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        results = []
        for row in rows:
            views = max(int(row["views"]), 0)
            retention = min(100, max(0, float(row["retention_pct"])))
            follows = max(int(row["followers_gained"]), 0)
            results.append({
                "platform": row["platform"], "views": views,
                "retention_pct": retention, "followers_gained": follows,
                "test_score": round(views / 1000 * retention / 100 + follows * 2, 2)
            })
        return {"rows": sorted(results, key=lambda x: x["test_score"], reverse=True),
                "note": "Local experiment score; not an audience prediction"}


class Factory:
    def run(self, topic_path: Path, output: Path, portrait: Path | None = None) -> dict[str, Any]:
        topic = TopicScoutAgent().discover(topic_path)
        FactCheckAgent().check(topic)
        slides = ScriptwriterAgent().draft(topic)
        review = QualityGateAgent().review(topic, slides)
        output.mkdir(parents=True, exist_ok=True)
        rendered = RenderAgent().video(
            slides, output / "cards", output / "preview.mp4", portrait
        )
        DistributionAgent().export(topic, output / "drafts")
        manifest = {
            "topic": topic.title, "slug": topic.slug,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "preview_requires_review", "video_generated": rendered,
            "source_urls": list(topic.sources), "storyboard": slides,
            "quality_gate": review
        }
        (output / "package.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline media-factory proof of concept")
    parser.add_argument("command", choices=("render", "analyze"))
    parser.add_argument("--topic", type=Path, default=ROOT / "examples/netflix.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/netflix")
    parser.add_argument("--portrait", type=Path, help="Local portrait only; never auto-uploaded")
    parser.add_argument("--metrics", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "render":
        result = Factory().run(args.topic, args.output, args.portrait)
        print(json.dumps({key: result[key] for key in
                          ("topic", "status", "video_generated")},
                         ensure_ascii=False, indent=2))
    else:
        if not args.metrics:
            parser.error("--metrics is required for analyze")
        print(json.dumps(AnalyticsAgent().report(args.metrics), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
