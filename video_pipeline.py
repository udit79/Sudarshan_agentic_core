"""
SIH 26154 - Video Generation Pipeline
Generates a complete video package (script, storyboard, narration, subtitles, visual recommendations)
from raw source content. Does NOT render an MP4 — it produces the production-ready package.
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field


# ============================================================================
# PART 1: SHARED MEMORY SYSTEM (Same as Advisory — will be imported later)
# ============================================================================

@dataclass
class Fact:
    text: str
    confidence: float = 1.0
    source: str = "extracted"

    def to_dict(self):
        return {"text": self.text, "confidence": self.confidence, "source": self.source}


@dataclass
class Entity:
    name: str
    entity_type: str

    def to_dict(self):
        return {"name": self.name, "type": self.entity_type}


@dataclass
class CaseMemory:
    case_id: str
    source_text: str
    entities: List[Entity] = field(default_factory=list)
    facts: List[Fact] = field(default_factory=list)
    artifacts: List[Dict] = field(default_factory=list)

    def add_fact(self, text: str, confidence: float = 1.0):
        self.facts.append(Fact(text, confidence))

    def add_entity(self, name: str, entity_type: str):
        self.entities.append(Entity(name, entity_type))

    def add_artifact(self, artifact_type: str, content: str, metadata: dict = None):
        self.artifacts.append({
            "type": artifact_type,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat()
        })


@dataclass
class UserMemory:
    user_id: str = "operator_001"
    tone: str = "formal"
    language: str = "en"
    classification_level: str = "RESTRICTED"
    domain: str = "cybersecurity"
    target_audience: str = "senior government officials"  # NEW for video


class Resolver:
    """Same resolver pattern — fetches scoped memory for the pipeline"""

    def __init__(self, case_memory: CaseMemory, user_memory: UserMemory):
        self.case = case_memory
        self.user = user_memory

    def resolve(self, scopes: List[str]) -> Dict:
        context = {}

        if "case" in scopes:
            context["case"] = {
                "source_text": self.case.source_text,
                "facts": [f.to_dict() for f in self.case.facts],
                "entities": [e.to_dict() for e in self.case.entities],
                "artifacts": self.case.artifacts
            }

        if "user" in scopes:
            context["user"] = {
                "tone": self.user.tone,
                "classification": self.user.classification_level,
                "domain": self.user.domain,
                "target_audience": self.user.target_audience
            }

        return context

    def write_back(self, scope: str, data: Dict):
        if scope == "case":
            self.case.add_artifact(
                data["type"],
                data["content"],
                data.get("metadata", {})
            )


# ============================================================================
# PART 2: MOCK LLM (Same interface — replace with OpenAI/Claude later)
# ============================================================================

class MockLLM:
    """Simulates LLM responses for video package generation"""

    def generate(self, prompt: str) -> str:
        # Detect tone and domain from prompt
        tone = "formal" if "formal" in prompt else "standard"
        is_urgent = "urgent" in prompt.lower() or "critical" in prompt.lower()

        return f"""
VIDEO PACKAGE: CYBER THREAT AWARENESS
Classification: RESTRICTED
Target Audience: Senior Government Officials
Produced: {datetime.now().strftime('%d %B %Y')}

---

## 1. SCRIPT (Scene-by-Scene)

**SCENE 1 — OPENING HOOK (0:00 - 0:15)**
*Visual: Dark screen. Slow pulse of red light. Government seal fades in.*
**NARRATION:** "In the last 72 hours, a sophisticated cyber campaign has targeted the highest levels of government. This is not a drill."

**SCENE 2 — THE THREAT (0:15 - 0:45)**
*Visual: Animated network diagram. Nodes lighting up in sequence.*
**NARRATION:** "APT29, also known as Cozy Bear, has launched a spear-phishing operation specifically designed to compromise senior officials across multiple ministries. The campaign uses spoofed domains that mirror official government portals with near-perfect accuracy."

**SCENE 3 — THE METHOD (0:45 - 1:20)**
*Visual: Split screen — legitimate email vs. malicious email. Highlight differences.*
**NARRATION:** "Attackers embed malicious PDF attachments exploiting a zero-day vulnerability. Once opened, these documents establish persistent backdoors, enabling long-term access to classified communications and internal networks."

**SCENE 4 — IMPACT (1:20 - 1:50)**
*Visual: Map showing affected ministries. Red indicators pulse.*
**NARRATION:** "The Ministry of Defence and Ministry of External Affairs have been specifically targeted. Compromise of these accounts could expose strategic plans, diplomatic communications, and operational timelines."

**SCENE 5 — WHAT YOU MUST DO (1:50 - 2:30)**
*Visual: Checklist animation. Clean, authoritative graphics.*
**NARRATION:** "Immediate actions required. One: Do not open unexpected attachments, even from known contacts. Two: Verify all login portals independently before entering credentials. Three: Report any suspicious communication to your security officer within 15 minutes. Four: Await further technical guidance from the National Technical Research Organisation."

**SCENE 6 — CLOSING (2:30 - 2:45)**
*Visual: NTRO logo. Secure lock icon. Calm blue background.*
**NARRATION:** "Vigilance is our first line of defence. The NTRO is actively monitoring this threat. Stay alert. Stay secure."

---

## 2. STORYBOARD (Scene-by-Scene Visual Plan)

| Scene | Duration | Visual Description | Camera/Style | Color Palette |
|-------|----------|-------------------|--------------|---------------|
| 1 | 0:15 | Dark void, single red pulse, seal emerges | Slow zoom, dramatic | Black, deep red, gold |
| 2 | 0:30 | Abstract network topology, nodes infecting | Isometric animation, data flow lines | Dark blue, electric cyan, red alerts |
| 3 | 0:35 | Side-by-side email comparison, vulnerability highlight | Split screen, magnifying glass effect | White, warning yellow, red |
| 4 | 0:30 | India map, ministry buildings highlighted | Flat 2D map, pulsing indicators | Slate grey, ministry colors, alert red |
| 5 | 0:40 | Animated checklist with checkmarks | Clean motion graphics, bold typography | White, NTRO blue, green checkmarks |
| 6 | 0:15 | NTRO crest, secure shield, calming gradient | Slow fade, reassuring | Deep blue, white, soft gold |

---

## 3. SCENE DESCRIPTIONS (Detailed)

**Scene 1 — Opening Hook**
- *Setting:* Abstract digital space
- *Mood:* Tense, authoritative, serious
- *Lighting:* Low-key, single source (red pulse)
- *Audio:* Deep bass drone, no music yet
- *Transition:* Hard cut to Scene 2

**Scene 2 — The Threat**
- *Setting:* Digital network visualization
- *Mood:* Analytical, revealing
- *Camera:* Slow pan across network nodes
- *Audio:* Subtle electronic ticking, data transmission sounds
- *Transition:* Smooth dissolve to Scene 3

**Scene 3 — The Method**
- *Setting:* Desktop/email interface mockup
- *Mood:* Educational, cautionary
- *Camera:* Static split-screen with animated highlights
- *Audio:* Mouse clicks, notification sounds (subtle)
- *Transition:* Zoom-out to map view

**Scene 4 — Impact**
- *Setting:* Strategic operations map
- *Mood:* Grave, consequential
- *Camera:* Bird's eye, slow zoom to affected regions
- *Audio:* Low drone, heartbeat rhythm
- *Transition:* Wipe to checklist

**Scene 5 — Action Items**
- *Setting:* Clean studio/graphics environment
- *Mood:* Directive, empowering, clear
- *Camera:* Static with animated text elements
- *Audio:* Confident, steady narration; subtle uplifting tone
- *Transition:* Fade to blue

**Scene 6 — Closing**
- *Setting:* NTRO branded environment
- *Mood:* Reassuring, resolved, professional
- *Camera:* Slow push-in on seal
- *Audio:* Resolve chord, calm ambient
- *Transition:* Fade to black

---

## 4. NARRATION TEXT (Full Voiceover Script)

[Scene 1]
"In the last 72 hours, a sophisticated cyber campaign has targeted the highest levels of government. This is not a drill."

[Scene 2]
"APT29, also known as Cozy Bear, has launched a spear-phishing operation specifically designed to compromise senior officials across multiple ministries. The campaign uses spoofed domains that mirror official government portals with near-perfect accuracy."

[Scene 3]
"Attackers embed malicious PDF attachments exploiting a zero-day vulnerability. Once opened, these documents establish persistent backdoors, enabling long-term access to classified communications and internal networks."

[Scene 4]
"The Ministry of Defence and Ministry of External Affairs have been specifically targeted. Compromise of these accounts could expose strategic plans, diplomatic communications, and operational timelines."

[Scene 5]
"Immediate actions required. One: Do not open unexpected attachments, even from known contacts. Two: Verify all login portals independently before entering credentials. Three: Report any suspicious communication to your security officer within 15 minutes. Four: Await further technical guidance from the National Technical Research Organisation."

[Scene 6]
"Vigilance is our first line of defence. The NTRO is actively monitoring this threat. Stay alert. Stay secure."

---

## 5. SUBTITLES (SRT Format)

1
00:00:00,000 --> 00:00:15,000
In the last 72 hours, a sophisticated
cyber campaign has targeted the highest
levels of government. This is not a drill.

2
00:00:15,000 --> 00:00:45,000
APT29, also known as Cozy Bear, has launched
a spear-phishing operation specifically designed
to compromise senior officials across multiple ministries.

3
00:00:45,000 --> 00:01:20,000
Attackers embed malicious PDF attachments
exploiting a zero-day vulnerability.

4
00:01:20,000 --> 00:01:50,000
The Ministry of Defence and Ministry of External
Affairs have been specifically targeted.

5
00:01:50,000 --> 00:02:30,000
Immediate actions required.
Do not open unexpected attachments.
Verify all login portals independently.

6
00:02:30,000 --> 00:02:45,000
Vigilance is our first line of defence.
Stay alert. Stay secure.

---

## 6. VISUAL RECOMMENDATIONS

**Color Palette:**
- Primary: Deep Navy (#0A192F) — authority, trust, government
- Accent: Alert Red (#FF2E2E) — urgency, threat, action required
- Highlight: Cyber Cyan (#00D4AA) — digital, technology, data
- Neutral: Slate Grey (#2D3748) — background, secondary info
- Warm: Institutional Gold (#C9A227) — seal, crest, official elements

**Typography:**
- Headlines: Montserrat Bold or Rajdhani Bold (clean, authoritative)
- Body: Open Sans or Roboto (readable, neutral)
- Data/Technical: JetBrains Mono or Fira Code (monospace for technical details)

**Imagery Style:**
- Photography: Desaturated, high-contrast government building shots
- Graphics: Flat 2D vector with subtle 3D depth
- Icons: Line-art style, single-weight stroke
- Maps: Minimalist, no topographical detail, focus on administrative boundaries

**B-Roll Suggestions:**
- Slow-motion shots of server rooms with blue LED lighting
- Hands typing on secure keyboards (close-up, shallow depth of field)
- Government building exteriors at dawn/dusk (symbolic: vigilance)
- Abstract data visualization flowing through fiber optic cables
- NTRO crest/logo animation (official, rotating seal)

**Music/Sound Design:**
- Opening: Deep sub-bass pulse, 60 BPM (heartbeat rhythm)
- Middle sections: Minimal electronic underscore, no melody (focus on narration)
- Action items: Slight rhythmic uplift, percussive elements (urgency without panic)
- Closing: Resolving chord, ambient pad, sense of completion and authority

**Technical Specs (Recommended):**
- Resolution: 1920x1080 (Full HD) or 3840x2160 (4K) for briefing rooms
- Aspect Ratio: 16:9 standard
- Frame Rate: 24fps (cinematic) or 30fps (standard broadcast)
- Audio: 48kHz stereo, narration centered, music -20dB below voice
"""


# ============================================================================
# PART 3: VIDEO PIPELINE
# ============================================================================

class VideoPipeline:
    """
    Transforms raw source content into a complete video production package.

    Output: Structured package containing script, storyboard, scene descriptions,
    narration text, subtitles (SRT), and visual recommendations.
    """

    def __init__(self, resolver: Resolver, llm_client):
        self.resolver = resolver
        self.llm = llm_client
        self.pipeline_name = "video"

    def _build_prompt(self, context: Dict) -> str:
        case = context["case"]
        user = context["user"]

        facts_text = "\n".join([f"- {f['text']}" for f in case["facts"]])
        entities_text = "\n".join([f"- {e['name']} ({e['type']})" for e in case["entities"]])

        prompt = f"""You are a senior NTRO communications producer and a defence media specialist.
Your task is to transform the following raw intelligence into a COMPLETE VIDEO PRODUCTION PACKAGE.
This package will be handed to a video production team to create a briefing video.

=== SOURCE CONTENT ===
{case['source_text']}

=== EXTRACTED FACTS ===
{facts_text}

=== IDENTIFIED ENTITIES ===
{entities_text}

=== USER PARAMETERS ===
- Tone: {user['tone']}
- Classification Level: {user['classification']}
- Target Audience: {user['target_audience']}
- Domain: {user['domain']}

=== OUTPUT REQUIREMENTS ===
Generate a complete video package with the following EXACT sections:

## 1. SCRIPT (Scene-by-Scene)
Write a scene-by-scene script with timestamps. Each scene must include:
- Scene number and title
- Duration (in seconds)
- Visual description (what appears on screen)
- Narration text (exact words to be spoken)

Target total duration: 2-3 minutes.
Narration style: {user['tone']}, authoritative, suitable for {user['target_audience']}.

## 2. STORYBOARD (Scene-by-Scene Visual Plan)
For each scene, provide:
- Visual description (what the camera sees)
- Camera angle/style suggestion
- Color palette for the scene
- Transition to next scene

## 3. SCENE DESCRIPTIONS (Detailed)
For each scene, provide:
- Setting (where it takes place)
- Mood/atmosphere
- Lighting description
- Audio design notes
- Transition notes

## 4. NARRATION TEXT (Full Voiceover Script)
Extract ONLY the spoken narration from the script into a clean, continuous text block.
This is what the voice actor will read.

## 5. SUBTITLES (SRT Format)
Generate proper SRT subtitle format with:
- Sequential subtitle numbers
- Timecodes (HH:MM:SS,mmm --> HH:MM:SS,mmm)
- Text broken into readable lines (max 2 lines per subtitle, max 40 chars per line)

## 6. VISUAL RECOMMENDATIONS
Provide detailed production guidance:
- Overall color palette (with hex codes if possible)
- Typography recommendations (font families)
- Imagery style (photography vs. graphics vs. animation)
- B-Roll footage suggestions
- Music and sound design notes
- Technical specs (resolution, aspect ratio, frame rate)

RULES:
- Do NOT include any classified details beyond the classification level provided.
- The video must be suitable for briefing room projection.
- Avoid sensationalism. Maintain government-grade professionalism.
- Ensure all recommendations are feasible with standard video production tools.
"""
        return prompt

    def _parse_video_package(self, raw_output: str) -> Dict:
        """
        Parses the raw LLM output into a structured video package.
        In production, use more robust parsing (regex or LLM JSON mode).
        """
        package = {
            "script": "",
            "storyboard": "",
            "scene_descriptions": "",
            "narration": "",
            "subtitles": "",
            "visual_recommendations": ""
        }

        # Simple section extraction using regex
        sections = {
            "script": r"## 1\. SCRIPT.*?(?=## 2\. STORYBOARD|$)",
            "storyboard": r"## 2\. STORYBOARD.*?(?=## 3\. SCENE DESCRIPTIONS|$)",
            "scene_descriptions": r"## 3\. SCENE DESCRIPTIONS.*?(?=## 4\. NARRATION TEXT|$)",
            "narration": r"## 4\. NARRATION TEXT.*?(?=## 5\. SUBTITLES|$)",
            "subtitles": r"## 5\. SUBTITLES.*?(?=## 6\. VISUAL RECOMMENDATIONS|$)",
            "visual_recommendations": r"## 6\. VISUAL RECOMMENDATIONS.*?(?=$)"
        }

        for key, pattern in sections.items():
            match = re.search(pattern, raw_output, re.DOTALL | re.IGNORECASE)
            if match:
                package[key] = match.group(0).strip()

        return package

    def _generate_srt_file(self, subtitles_text: str, case_id: str) -> str:
        """Extracts clean SRT content for file export"""
        # Find the actual SRT content (numbered entries with timecodes)
        srt_match = re.search(r'(\d+\s+\d{2}:\d{2}:\d{2},\d{3}\s+-->', subtitles_text, re.DOTALL)
        if srt_match:
            # Return from the first subtitle number onwards
            start_idx = subtitles_text.find("1\n00:")
            if start_idx != -1:
                return subtitles_text[start_idx:].strip()
        return subtitles_text.strip()

    def run(self) -> Dict:
        print(f"\n{'=' * 60}")
        print(f"PIPELINE: {self.pipeline_name.upper()}")
        print(f"{'=' * 60}")

        # Step 1: ALLOCATE MEMORY
        print("\n[1] ALLOCATING MEMORY (Resolver)...")
        context = self.resolver.resolve(scopes=["case", "user"])
        print(f"    ✓ Fetched {len(context['case']['facts'])} facts")
        print(f"    ✓ Fetched {len(context['case']['entities'])} entities")
        print(f"    ✓ Target audience: {context['user']['target_audience']}")

        # Step 2: BUILD PROMPT
        print("\n[2] BUILDING VIDEO PROMPT...")
        prompt = self._build_prompt(context)
        print(f"    ✓ Prompt length: {len(prompt)} characters")

        # Step 3: GENERATE
        print("\n[3] GENERATING VIDEO PACKAGE (LLM)...")
        raw_output = self.llm.generate(prompt)
        print(f"    ✓ Generated {len(raw_output)} characters")

        # Step 4: PARSE STRUCTURED PACKAGE
        print("\n[4] PARSING VIDEO PACKAGE...")
        package = self._parse_video_package(raw_output)
        for key in package:
            status = "✓" if package[key] else "✗"
            print(f"    {status} {key}: {len(package[key])} chars")

        # Step 5: FORMAT OUTPUT
        print("\n[5] FORMATTING OUTPUT...")
        formatted = self._format_package_output(package)

        # Step 6: WRITE BACK
        print("\n[6] WRITING BACK TO MEMORY...")
        self.resolver.write_back("case", {
            "type": "video_package",
            "content": formatted,
            "metadata": {
                "pipeline": self.pipeline_name,
                "sections": list(package.keys()),
                "total_duration_estimate": "2:45",
                "scene_count": len(re.findall(r'SCENE \d+', package.get("script", ""))),
                "has_subtitles": bool(package.get("subtitles")),
                "word_count": len(formatted.split())
            }
        })
        print("    ✓ Video package saved to Case Memory")

        return {
            "status": "success",
            "pipeline": self.pipeline_name,
            "package": package,
            "content": formatted,
            "metadata": {
                "facts_used": len(context["case"]["facts"]),
                "prompt_length": len(prompt),
                "sections_generated": [k for k, v in package.items() if v]
            }
        }

    def _format_package_output(self, package: Dict) -> str:
        """Combines all sections into a single deliverable document"""
        sections = []
        for key in ["script", "storyboard", "scene_descriptions",
                    "narration", "subtitles", "visual_recommendations"]:
            if package.get(key):
                sections.append(package[key])
                sections.append("\n" + "=" * 60 + "\n")
        return "\n".join(sections)


# ============================================================================
# PART 4: EXTRACTOR (Same pattern — populates Case Memory)
# ============================================================================

class SimpleExtractor:
    """Extracts narrative elements relevant to video production"""

    def extract(self, text: str, case_memory: CaseMemory):
        # Extract temporal markers (for video pacing)
        dates = re.findall(
            r'\b\d{{1,2}}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{{4}}\b',
            text)
        for date in dates:
            case_memory.add_fact(f"Timeline marker: {date}", confidence=0.9)

        # Extract threat actors (characters in the video narrative)
        threat_actors = ["APT29", "APT28", "Lazarus", "Cozy Bear", "Fancy Bear"]
        for actor in threat_actors:
            if actor in text:
                case_memory.add_entity(actor, "threat_actor")
                case_memory.add_fact(f"Primary antagonist: {actor}", confidence=0.95)

        # Extract attack techniques (visual elements)
        techniques = ["phishing", "spear-phishing", "malware", "ransomware",
                      "DDoS", "supply chain", "credential stuffing", "backdoor"]
        for tech in techniques:
            if tech in text.lower():
                case_memory.add_entity(tech, "attack_technique")
                case_memory.add_fact(f"Visual element: {tech} attack method", confidence=0.85)

        # Extract targets (stakeholders in the video)
        targets = ["government officials", "Ministry", "defence sector",
                   "critical infrastructure", "financial institutions", "senior officials"]
        for target in targets:
            if target in text.lower():
                case_memory.add_entity(target, "target_audience")
                case_memory.add_fact(f"Stakeholder group: {target}", confidence=0.8)

        # Extract urgency indicators (pacing cues)
        urgency_words = ["immediate", "urgent", "critical", "ongoing", "active"]
        for word in urgency_words:
            if word in text.lower():
                case_memory.add_fact(f"Pacing cue: {word} threat level", confidence=0.75)

        case_memory.add_fact(f"Source narrative: {text[:200]}...", confidence=1.0)

        print(f"    ✓ Extracted {len(case_memory.facts)} facts")
        print(f"    ✓ Extracted {len(case_memory.entities)} entities")


# ============================================================================
# PART 5: MAIN — Run standalone
# ============================================================================

def main():
    # Same raw report as advisory, but now we want a VIDEO
    raw_report = """
    INTELLIGENCE BRIEF: APT29 Spear-Phishing Campaign

    On 15 August 2026, NTRO cyber defense units detected a sophisticated 
    spear-phishing campaign attributed to APT29 (Cozy Bear). The campaign 
    specifically targets senior government officials across multiple ministries.

    Attackers are using spoofed email domains that mimic official government 
    portals. Emails contain malicious PDF attachments that exploit a recently 
    disclosed vulnerability. Initial analysis suggests the objective is 
    credential harvesting and persistent network access.

    Affected targets include Ministry of Defence and Ministry of External 
    Affairs personnel. The campaign shows high sophistication with customized 
    lures referencing current government initiatives.
    """

    print("=" * 60)
    print("SIH 26154 — VIDEO PIPELINE DEMO")
    print("=" * 60)

    # Step 1: Create Case Memory
    print("\n[INIT] Creating Case Memory...")
    case = CaseMemory(
        case_id="CASE-2026-001-VIDEO",
        source_text=raw_report
    )

    # Step 2: Extract narrative elements
    print("\n[EXTRACT] Populating Graph Memory...")
    extractor = SimpleExtractor()
    extractor.extract(raw_report, case)

    # Step 3: Set up User Memory
    user = UserMemory(
        tone="formal",
        classification_level="RESTRICTED",
        target_audience="senior government officials"
    )

    # Step 4: Resolver
    resolver = Resolver(case, user)

    # Step 5: LLM
    llm = MockLLM()

    # Step 6: RUN VIDEO PIPELINE
    pipeline = VideoPipeline(resolver, llm)
    result = pipeline.run()

    # Step 7: Display results
    print(f"\n{'=' * 60}")
    print("RESULT")
    print(f"{'=' * 60}")
    print(f"\nStatus: {result['status']}")
    print(f"Pipeline: {result['pipeline']}")
    print(f"Facts used: {result['metadata']['facts_used']}")
    print(f"Sections generated: {', '.join(result['metadata']['sections_generated'])}")

    print(f"\n{'=' * 60}")
    print("GENERATED VIDEO PACKAGE")
    print(f"{'=' * 60}")
    print(result['content'][:2000])  # Print first 2000 chars
    print("\n... [truncated for display] ...")

    print(f"\n{'=' * 60}")
    print("MEMORY STATE (Case Artifacts)")
    print(f"{'=' * 60}")
    for artifact in case.artifacts:
        print(f"  → Type: {artifact['type']}")
        print(f"    Sections: {', '.join(artifact['metadata']['sections'])}")
        print(f"    Est. Duration: {artifact['metadata']['total_duration_estimate']}")
        print(f"    Scene Count: {artifact['metadata']['scene_count']}")
        print(f"    Saved at: {artifact['created_at']}")

    # Save individual files
    package = result["package"]

    with open("video_script.txt", "w") as f:
        f.write(package.get("script", ""))
    print(f"\n✓ Saved script to video_script.txt")

    with open("video_narration.txt", "w") as f:
        f.write(package.get("narration", ""))
    print(f"✓ Saved narration to video_narration.txt")

    with open("video_subtitles.srt", "w") as f:
        srt_content = pipeline._generate_srt_file(package.get("subtitles", ""), case.case_id)
        f.write(srt_content)
    print(f"✓ Saved subtitles to video_subtitles.srt")

    with open("video_full_package.md", "w") as f:
        f.write(result["content"])
    print(f"✓ Saved full package to video_full_package.md")


if __name__ == "__main__":
    main()