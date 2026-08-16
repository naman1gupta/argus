import random
from datetime import timedelta
from decimal import Decimal

from argus.pricing import estimate_cost
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.chat.models import Message, Session, new_ulid
from apps.projects.models import Project
from apps.telemetry.models import InferenceLog

MODELS = [
    ("anthropic", "claude-sonnet-4-5", 0.35, 900),
    ("anthropic", "claude-haiku-4-5", 0.10, 450),
    ("gcp.gemini", "gemini-2.5-flash", 0.25, 600),
    ("groq", "llama-3.3-70b-versatile", 0.20, 300),
    ("mock", "argus-demo-1", 0.10, 350),
]
ERROR_TYPES = ["RateLimitError", "OverloadedError", "APITimeoutError", "InvalidRequestError"]
PROMPTS = [
    ("What is your refund policy for damaged goods?", [], False),
    ("Summarize the onboarding document for a new support agent", [], False),
    ("My order is #48291, email is <EMAIL> — check the status please", ["EMAIL"], True),
    ("Draft an apology email to <EMAIL> for the delayed shipment", ["EMAIL"], True),
    ("Explain Kafka consumer group rebalancing simply", [], False),
    ("Card ending <CREDIT_CARD> was charged twice, I need a reversal", ["CREDIT_CARD"], True),
    ("Call me at <PHONE_IN> when the ticket is resolved", ["PHONE_IN"], True),
    ("Translate this support macro into Hindi and Spanish", [], False),
    ("Generate five subject lines for the win-back campaign", [], False),
]
RESPONSES = [
    "Certainly — here's a concise answer based on the current policy and your account state.",
    "I reviewed the details and drafted the response you asked for; flag any edge cases.",
    "Done. The summary covers the three key sections with action items highlighted.",
    "That behavior comes from partition ownership; here's the intuition and a concrete example.",
]


class Command(BaseCommand):
    help = "Seeds ~7 days of realistic demo telemetry plus a few replayable chat sessions."

    def add_arguments(self, parser):
        parser.add_argument("--events", type=int, default=6000)

    def handle(self, *args, **options):
        random.seed(42)
        project = Project.objects.first()
        if project is None:
            self.stderr.write("run bootstrap_demo first")
            return
        if InferenceLog.objects.filter(environment="demo").exists():
            self.stdout.write("demo data already present, skipping (delete env='demo' to reseed)")
            return

        now = timezone.now()
        users = ["member", "priya", "arjun", "demo-bot"]
        session_pool = [f"seed_{new_ulid()}" for _ in range(40)]
        rows = []
        n = options["events"]
        for _ in range(n):
            # denser toward recent hours; one simulated incident window ~26h ago
            age_h = random.random() ** 1.6 * 168
            ts = now - timedelta(hours=age_h, seconds=random.randint(0, 3599))
            provider, model, _, base_ttft = random.choices(
                MODELS, weights=[m[2] for m in MODELS]
            )[0]
            incident = 25 <= age_h <= 27
            is_error = random.random() < (0.18 if incident else 0.018)
            is_aborted = not is_error and random.random() < 0.012
            prompt, entities, masked = random.choice(PROMPTS)
            ttft = random.lognormvariate(0, 0.35) * base_ttft
            latency = ttft + random.lognormvariate(0, 0.5) * 1200
            tin = random.randint(80, 2200)
            tout = random.randint(30, 700)
            status = "error" if is_error else ("aborted" if is_aborted else "success")
            cost = estimate_cost(provider, model, tin, tout) if status == "success" else None
            rows.append(
                InferenceLog(
                    generation_id=f"gen_{new_ulid()}",
                    project_id=project.id,
                    session_id=random.choice(session_pool),
                    end_user_id=random.choice(users),
                    provider=provider,
                    request_model=model,
                    response_model=model if status == "success" else "",
                    is_streaming=random.random() < 0.9,
                    status=status,
                    error_type=random.choice(ERROR_TYPES) if is_error else "",
                    error_message="simulated for demo data" if is_error else "",
                    started_at=ts,
                    first_chunk_at=None if is_error else ts + timedelta(milliseconds=ttft),
                    completed_at=ts + timedelta(milliseconds=latency),
                    latency_ms=round(latency if not is_error else random.uniform(50, 400), 1),
                    ttft_ms=None if is_error else round(ttft, 1),
                    input_tokens=None if is_error else tin,
                    output_tokens=None if is_error else tout,
                    tokens_estimated=is_aborted,
                    cost_usd=Decimal(str(cost)) if cost is not None else None,
                    finish_reasons=["stop"] if status == "success" else [],
                    prompt_preview=prompt,
                    response_preview=random.choice(RESPONSES) if status == "success" else "",
                    pii_masked=masked,
                    pii_entities_found=entities,
                    environment="demo",
                )
            )
        InferenceLog.objects.bulk_create(rows, batch_size=1000)
        self._seed_chat_sessions(project)
        self.stdout.write(self.style.SUCCESS(f"seeded {n} telemetry rows + demo chat sessions"))

    def _seed_chat_sessions(self, project):
        User = get_user_model()
        member = User.objects.filter(username="member").first()
        convos = [
            ("Refund policy for damaged goods",
             [("user", "What's your refund policy if the product arrived damaged?"),
              ("assistant", "If your product arrived damaged you're covered — full refund or free "
               "replacement within 30 days of delivery. I'll need the order number and a photo."),
              ("user", "Order #48291, my email is <EMAIL>"),
              ("assistant", "Noted — claim opened for #48291. You'll get a confirmation email; "
               "refunds land 3-5 business days after review.")]),
            ("Kafka consumer rebalancing help",
             [("user", "Explain Kafka consumer group rebalancing like I'm five"),
              ("assistant", "Imagine toys (partitions) shared between kids (consumers). When a kid "
               "joins or leaves, toys get re-shared so everyone holds some — a rebalance.")]),
        ]  # fmt: skip
        for title, turns in convos:
            if Session.objects.filter(title=title).exists():
                continue
            s = Session.objects.create(user=member, project=project, title=title)
            for seq, (role, content) in enumerate(turns):
                Message.objects.create(
                    session=s, role=role, content=content, seq=seq,
                    provider="mock" if role == "assistant" else "",
                    model="argus-demo-1" if role == "assistant" else "",
                )  # fmt: skip
            # matching telemetry rows so session replay shows per-turn chips
            ts = timezone.now() - timedelta(hours=2)
            for j, (role, content) in enumerate(turns):
                if role != "assistant":
                    continue
                InferenceLog.objects.create(
                    generation_id=f"gen_{new_ulid()}",
                    project_id=project.id,
                    session_id=s.id,
                    end_user_id="member",
                    provider="mock",
                    request_model="argus-demo-1",
                    response_model="argus-demo-1",
                    is_streaming=True,
                    status="success",
                    started_at=ts + timedelta(minutes=j),
                    first_chunk_at=ts + timedelta(minutes=j, milliseconds=350),
                    completed_at=ts + timedelta(minutes=j, milliseconds=1400),
                    latency_ms=1400.0,
                    ttft_ms=350.0,
                    input_tokens=len(content) // 3,
                    output_tokens=len(content) // 4,
                    cost_usd=Decimal("0"),
                    finish_reasons=["stop"],
                    prompt_preview=turns[max(j - 1, 0)][1][:200],
                    response_preview=content[:200],
                    pii_masked="<EMAIL>" in turns[max(j - 1, 0)][1],
                    pii_entities_found=["EMAIL"] if "<EMAIL>" in turns[max(j - 1, 0)][1] else [],
                    environment="demo",
                )
