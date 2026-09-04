"""
SIH 26154 - Advisory Generation Pipeline
A complete, runnable pipeline that transforms raw content into a structured NTRO advisory.
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum


# ============================================================================
# PART 1: MEMORY SYSTEM (The "Graph Memory" simplified)
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
    entity_type: str  # threat_actor, target, technique, etc.

    def to_dict(self):
        return {"name": self.name, "type": self.entity_type}


@dataclass
class CaseMemory:
    """Your teammate's 'Graph Memory' — just a Python object"""
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
    """User preferences — long-term memory"""
    user_id: str = "operator_001"
    tone: str = "formal"
    language: str = "en"
    classification_level: str = "RESTRICTED"
    domain: str = "cybersecurity"


# ============================================================================
# PART 2: RESOLVER (The "Allocation" logic — who reads what)
# ============================================================================

class Resolver:
    """
    The Resolver decides WHICH memory each pipeline gets.
    For Advisory: we need case facts + user tone preferences.
    """

    def __init__(self, case_memory: CaseMemory, user_memory: UserMemory):
        self.case = case_memory
        self.user = user_memory

    def resolve(self, scopes: List[str]) -> Dict:
        """
        scopes: ["case", "user"] or ["case", "user", "task"]
        This is the 'memory allocation' — we fetch only what's needed.
        """
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
                "domain": self.user.domain
            }

        return context

    def write_back(self, scope: str, data: Dict):
        """Write generated output back to memory"""
        if scope == "case":
            self.case.add_artifact(
                data["type"],
                data["content"],
                data.get("metadata", {})
            )


# ============================================================================
# PART 3: THE LLM CLIENT (Mock for testing, replace with real API)
# ============================================================================

class MockLLM:
    """
    Fake LLM for testing without API keys.
    Replace this with OpenAI/Claude client in production.
    """

    def generate(self, prompt: str) -> str:
        """Simulates an LLM response based on prompt keywords"""

        # Extract facts from the prompt to make it look realistic
        facts = re.findall(r'- (.+)', prompt)
        tone = "formal" if "formal" in prompt else "standard"

        # Build a realistic advisory structure
        situation = facts[0] if facts else "A significant security incident has been detected."

        return f"""
## SITUATION
{situation} This activity poses a credible threat to government infrastructure and requires immediate attention from security teams.

## THREAT ASSESSMENT
Based on analysis of available intelligence, the threat actor has demonstrated sophisticated capabilities including social engineering and credential harvesting. The campaign appears to be ongoing and targeted specifically at senior government officials with access to sensitive systems.

Key indicators:
- Use of spoofed domains mimicking official government portals
- Sophisticated spear-phishing emails with malicious attachments
- Command and control infrastructure hosted on compromised legitimate services

## IMPACT ANALYSIS
**Immediate Impact:** Potential compromise of official email accounts and unauthorized access to classified communications.
**Strategic Impact:** If successful, this campaign could enable persistent access to government networks, facilitating espionage or disruptive operations.

## RECOMMENDATIONS
1. **Immediate Network Review:** Conduct urgent analysis of email gateway logs for indicators associated with this campaign.
2. **Credential Reset:** Force password resets for all identified targets and implement multi-factor authentication where not already deployed.
3. **User Awareness:** Issue targeted security advisory to all personnel with emphasis on recognizing sophisticated phishing attempts.
4. **Threat Hunting:** Deploy threat hunting teams to identify potential compromise indicators across the network perimeter.

## ACTION ITEMS
| Priority | Action | Responsible | Timeline |
|----------|--------|-------------|----------|
| P1 | Isolate affected email accounts | SOC Team | 24 hours |
| P1 | Block identified malicious domains | Network Team | 4 hours |
| P2 | Deploy enhanced email filtering | Security Team | 48 hours |
| P2 | Conduct organization-wide phishing drill | Training Unit | 1 week |
| P3 | Submit IOCs to national CERT | Intel Team | 72 hours |

---
**Classification:** RESTRICTED  
**Distribution:** Senior Security Personnel Only  
**Produced by:** NTRO Automated Content Transformation Platform  
**Date:** {datetime.now().strftime('%d %B %Y')}
"""


class RealLLM:
    """Replace MockLLM with this when you have an API key"""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model
        # import openai
        # self.client = openai.OpenAI(api_key=api_key)

    def generate(self, prompt: str) -> str:
        # response = self.client.chat.completions.create(
        #     model=self.model,
        #     messages=[{"role": "user", "content": prompt}],
        #     temperature=0.3,
        #     max_tokens=2000
        # )
        # return response.choices[0].message.content
        pass


# ============================================================================
# PART 4: THE ADVISORY PIPELINE (The actual pipeline)
# ============================================================================

class AdvisoryPipeline:
    """
    Transforms raw source content into a structured NTRO advisory document.

    This is what your teammate calls the "Advisory Generation Agent".
    It's just: fetch context → build prompt → call LLM → format output → save to memory.
    """

    def __init__(self, resolver: Resolver, llm_client):
        self.resolver = resolver
        self.llm = llm_client
        self.pipeline_name = "advisory"

    def _build_prompt(self, context: Dict) -> str:
        """
        Builds the LLM prompt from resolved memory context.
        This is the 'Agent' — it's just a carefully written instruction.
        """
        case = context["case"]
        user = context["user"]

        # Format facts for the prompt
        facts_text = "\n".join([f"- {f['text']} (confidence: {f['confidence']})"
                                for f in case["facts"]])

        # Format entities
        entities_text = "\n".join([f"- {e['name']} ({e['type']})"
                                   for e in case["entities"]])

        prompt = f"""You are a senior analyst at the National Technical Research Organisation (NTRO).
Your task is to transform the following raw intelligence into a formal, structured advisory document.

=== SOURCE CONTENT ===
{case['source_text']}

=== EXTRACTED FACTS ===
{facts_text}

=== IDENTIFIED ENTITIES ===
{entities_text}

=== USER PARAMETERS ===
- Tone: {user['tone']}
- Classification Level: {user['classification']}
- Domain Expertise: {user['domain']}

=== OUTPUT REQUIREMENTS ===
Generate a structured advisory with the following exact sections:

## SITUATION
A concise 2-3 paragraph summary of the issue, its scope, and why it matters.

## THREAT ASSESSMENT
Detailed technical and contextual analysis. Include:
- Capabilities of threat actors involved
- Methods and techniques observed
- Evidence quality and confidence levels

## IMPACT ANALYSIS
Evaluate both immediate and strategic impacts:
- Immediate: What is happening right now?
- Strategic: What could happen if unaddressed?

## RECOMMENDATIONS
Provide 3-5 specific, actionable recommendations. Each must be:
- Concrete (who should do what)
- Prioritized (most critical first)
- Realistic (feasible with available resources)

## ACTION ITEMS
Present as a markdown table with columns:
| Priority | Action | Responsible Party | Timeline |

Use professional government security language. Be precise, avoid speculation beyond the provided facts, and clearly distinguish between confirmed facts and analytical assessments.
"""
        return prompt

    def run(self) -> Dict:
        """
        Main pipeline execution.
        1. ALLOCATE MEMORY (read) → 2. GENERATE → 3. WRITE BACK (allocate write)
        """
        print(f"\n{'=' * 60}")
        print(f"PIPELINE: {self.pipeline_name.upper()}")
        print(f"{'=' * 60}")

        # Step 1: ALLOCATE MEMORY — fetch what this pipeline needs
        print("\n[1] ALLOCATING MEMORY (Resolver)...")
        context = self.resolver.resolve(scopes=["case", "user"])
        print(f"    ✓ Fetched {len(context['case']['facts'])} facts")
        print(f"    ✓ Fetched {len(context['case']['entities'])} entities")
        print(f"    ✓ User tone: {context['user']['tone']}")

        # Step 2: BUILD PROMPT
        print("\n[2] BUILDING PROMPT...")
        prompt = self._build_prompt(context)
        print(f"    ✓ Prompt length: {len(prompt)} characters")

        # Step 3: GENERATE (call LLM)
        print("\n[3] GENERATING ADVISORY (LLM)...")
        raw_output = self.llm.generate(prompt)
        print(f"    ✓ Generated {len(raw_output)} characters")

        # Step 4: FORMAT OUTPUT
        print("\n[4] FORMATTING OUTPUT...")
        formatted = self._format_output(raw_output)

        # Step 5: WRITE BACK — save to memory
        print("\n[5] WRITING BACK TO MEMORY...")
        self.resolver.write_back("case", {
            "type": "advisory",
            "content": formatted,
            "metadata": {
                "pipeline": self.pipeline_name,
                "word_count": len(formatted.split()),
                "sections": self._extract_sections(raw_output)
            }
        })
        print("    ✓ Artifact saved to Case Memory")

        return {
            "status": "success",
            "pipeline": self.pipeline_name,
            "content": formatted,
            "metadata": {
                "facts_used": len(context["case"]["facts"]),
                "prompt_length": len(prompt)
            }
        }

    def _format_output(self, raw: str) -> str:
        """Clean up LLM output — remove extra whitespace, ensure headers"""
        lines = raw.strip().split("\n")
        cleaned = []
        for line in lines:
            if line.strip():
                cleaned.append(line.rstrip())
        return "\n".join(cleaned)

    def _extract_sections(self, text: str) -> List[str]:
        """Track which sections were generated"""
        sections = []
        for section in ["SITUATION", "THREAT ASSESSMENT", "IMPACT ANALYSIS",
                        "RECOMMENDATIONS", "ACTION ITEMS"]:
            if section in text.upper():
                sections.append(section)
        return sections


# ============================================================================
# PART 5: EXTRACTOR (Populates Case Memory from raw text)
# ============================================================================

class SimpleExtractor:
    """
    Extracts structured facts/entities from raw text.
    In production, this calls an LLM. For demo, we use regex/rules.
    """

    def extract(self, text: str, case_memory: CaseMemory):
        """Populates case memory with extracted information"""

        # Extract dates
        dates = re.findall(
            r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
            text)
        for date in dates:
            case_memory.add_fact(f"Event date identified: {date}", confidence=0.9)

        # Extract threat actors (simple keyword matching)
        threat_actors = ["APT29", "APT28", "Lazarus", "Cozy Bear", "Fancy Bear"]
        for actor in threat_actors:
            if actor in text:
                case_memory.add_entity(actor, "threat_actor")
                case_memory.add_fact(f"Threat actor identified: {actor}", confidence=0.95)

        # Extract attack techniques
        techniques = ["phishing", "spear-phishing", "malware", "ransomware",
                      "DDoS", "supply chain", "credential stuffing"]
        for tech in techniques:
            if tech in text.lower():
                case_memory.add_entity(tech, "attack_technique")
                case_memory.add_fact(f"Attack technique observed: {tech}", confidence=0.85)

        # Extract targets
        targets = ["government officials", "Ministry", "defense sector",
                   "critical infrastructure", "financial institutions"]
        for target in targets:
            if target in text.lower():
                case_memory.add_entity(target, "target")
                case_memory.add_fact(f"Target identified: {target}", confidence=0.8)

        # Add the raw text as a fact too
        case_memory.add_fact(f"Source report summary: {text[:200]}...", confidence=1.0)

        print(f"    ✓ Extracted {len(case_memory.facts)} facts")
        print(f"    ✓ Extracted {len(case_memory.entities)} entities")


# ============================================================================
# PART 6: MAIN — Run the complete pipeline
# ============================================================================

def main():
    # Raw input — a threat report (this would come from user upload)
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
    print("SIH 26154 — ADVISORY PIPELINE DEMO")
    print("=" * 60)

    # Step 1: Create Case Memory
    print("\n[INIT] Creating Case Memory...")
    case = CaseMemory(
        case_id="CASE-2026-001",
        source_text=raw_report
    )

    # Step 2: Extract structured info (populate graph memory)
    print("\n[EXTRACT] Populating Graph Memory...")
    extractor = SimpleExtractor()
    extractor.extract(raw_report, case)

    # Step 3: Set up User Memory (operator preferences)
    user = UserMemory(
        tone="formal",
        classification_level="RESTRICTED"
    )

    # Step 4: Create Resolver (connects memory to pipeline)
    resolver = Resolver(case, user)

    # Step 5: Create LLM client (mock for demo)
    llm = MockLLM()

    # Step 6: RUN THE PIPELINE
    pipeline = AdvisoryPipeline(resolver, llm)
    result = pipeline.run()

    # Step 7: Display results
    print(f"\n{'=' * 60}")
    print("RESULT")
    print(f"{'=' * 60}")
    print(f"\nStatus: {result['status']}")
    print(f"Pipeline: {result['pipeline']}")
    print(f"Facts used: {result['metadata']['facts_used']}")
    print(f"Prompt length: {result['metadata']['prompt_length']} chars")

    print(f"\n{'=' * 60}")
    print("GENERATED ADVISORY")
    print(f"{'=' * 60}")
    print(result['content'])

    print(f"\n{'=' * 60}")
    print("MEMORY STATE (Case Artifacts)")
    print(f"{'=' * 60}")
    for artifact in case.artifacts:
        print(f"  → Type: {artifact['type']}")
        print(f"    Word count: {artifact['metadata']['word_count']}")
        print(f"    Sections: {', '.join(artifact['metadata']['sections'])}")
        print(f"    Saved at: {artifact['created_at']}")

    # Save to file
    filename = "advisory_output.md"
    with open(filename, "w") as f:
        f.write(result['content'])
    print(f"\n✓ Saved to {filename}")


if __name__ == "__main__":
    main()