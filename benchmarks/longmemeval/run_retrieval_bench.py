#!/usr/bin/env python3
"""LongMemEval 검색 품질 벤치마크 (LLM 불필요)

mock 데이터셋으로 mem-mesh의 index → retrieve → recall/NDCG를 측정합니다.
다양한 질문 유형 (단일 세션, 다중 세션, 시간 추론, 지식 업데이트, 기권)을 포함합니다.

Usage:
    python benchmarks/longmemeval/run_retrieval_bench.py
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import List

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.schemas.requests import SearchParams
from app.core.schemas.responses import SearchResponse
from app.core.storage.direct import DirectStorageBackend

from benchmarks.longmemeval.indexer import create_indexer
from benchmarks.longmemeval.models import BenchmarkItem, QuestionResult, RetrievalMetrics
from benchmarks.longmemeval.reporter import generate_report, print_report
from benchmarks.longmemeval.retriever import Retriever


def _sqlite_vec_available() -> bool:
    """sqlite-vec 사용 가능 여부 확인"""
    try:
        from app.core.database.base import SQLITE_VEC_AVAILABLE
        return SQLITE_VEC_AVAILABLE
    except ImportError:
        return False


def _patch_search_for_fuzzy(storage: DirectStorageBackend) -> None:
    """sqlite-vec 미사용 시 fuzzy search로 폴백"""

    async def _fuzzy_search_wrapper(params: SearchParams) -> SearchResponse:
        if not storage.unified_search_service:
            raise RuntimeError("UnifiedSearchService not initialized")
        return await storage.unified_search_service.search(
            query=params.query,
            project_id=params.project_id,
            category=params.category,
            limit=params.limit,
            recency_weight=params.recency_weight,
            search_mode="fuzzy",
            time_range=params.time_range,
            date_from=params.date_from,
            date_to=params.date_to,
            temporal_mode=params.temporal_mode,
        )

    storage._search_with_unified_service = _fuzzy_search_wrapper  # type: ignore[assignment]

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_mock_dataset() -> List[BenchmarkItem]:
    """다양한 질문 유형의 mock 데이터셋 생성 (20개 질문)"""
    items: List[BenchmarkItem] = []

    # === 1. Single-Session Info Extraction (5개) ===
    items.append(BenchmarkItem(
        question_id="q_001",
        question_type="single-session-user-centric",
        question="What is Alice's favorite programming language?",
        answer="Python",
        haystack_sessions=[
            [
                "User: Hey Alice, what programming language do you like the most?",
                "Assistant: I really love Python! It's so versatile and readable.",
                "User: Why do you prefer Python over other languages?",
                "Assistant: Python has great libraries for data science and ML, plus its syntax is clean and elegant.",
            ],
            [
                "User: What did you have for lunch today?",
                "Assistant: I had a nice pasta with marinara sauce and a side salad.",
            ],
            [
                "User: Can you recommend a good movie?",
                "Assistant: I'd recommend Inception by Christopher Nolan. It's a mind-bending thriller.",
            ],
        ],
        haystack_dates=["2024/03/15 Friday 14:30", "2024/03/16 Saturday 12:00", "2024/03/17 Sunday 19:00"],
        answer_session_ids=[0],
    ))

    items.append(BenchmarkItem(
        question_id="q_002",
        question_type="single-session-user-centric",
        question="What breed is Bob's dog?",
        answer="Golden Retriever named Max",
        haystack_sessions=[
            [
                "User: I just adopted a new cat. She's a Persian.",
                "Assistant: Persian cats are beautiful! What did you name her?",
            ],
            [
                "User: My dog Max is a Golden Retriever. He loves swimming.",
                "Assistant: Golden Retrievers are wonderful dogs! Swimming is great exercise for them.",
                "User: He's 3 years old and very energetic.",
                "Assistant: That's a great age. Golden Retrievers typically have lots of energy until they're about 5.",
            ],
            [
                "User: What's the weather like today?",
                "Assistant: It's partly cloudy with a high of 72°F. Perfect weather for a walk with Max!",
            ],
        ],
        haystack_dates=["2024/03/10 Sunday 09:00", "2024/03/12 Tuesday 15:00", "2024/03/14 Thursday 10:00"],
        answer_session_ids=[1],
    ))

    items.append(BenchmarkItem(
        question_id="q_003",
        question_type="single-session-user-centric",
        question="What instrument does Carol play?",
        answer="Piano, been playing for 15 years",
        haystack_sessions=[
            [
                "User: I've been playing piano for 15 years now.",
                "Assistant: That's impressive! 15 years of piano is quite a commitment. Do you perform?",
                "User: Yes, I play at local jazz clubs on weekends.",
                "Assistant: Jazz piano is wonderful. Do you have a favorite jazz pianist?",
                "User: Bill Evans is my biggest inspiration.",
                "Assistant: Bill Evans had such a lyrical touch. His album 'Waltz for Debby' is a masterpiece.",
            ],
            [
                "User: I need help with my tax return.",
                "Assistant: I can help with general tax questions. What specific aspect do you need help with?",
            ],
        ],
        haystack_dates=["2024/02/20 Tuesday 20:00", "2024/03/01 Friday 10:00"],
        answer_session_ids=[0],
    ))

    items.append(BenchmarkItem(
        question_id="q_004",
        question_type="single-session-user-centric",
        question="What is Dave's job title?",
        answer="Senior DevOps Engineer at CloudScale",
        haystack_sessions=[
            [
                "User: Can you help me debug this Kubernetes deployment?",
                "Assistant: Sure! What error are you seeing in the deployment logs?",
            ],
            [
                "User: As a Senior DevOps Engineer at CloudScale, I manage our entire CI/CD pipeline.",
                "Assistant: That sounds like a significant responsibility. What tools do you use for CI/CD?",
                "User: We use GitHub Actions, ArgoCD, and Terraform for infrastructure.",
                "Assistant: That's a solid stack. ArgoCD is great for GitOps-style deployments.",
            ],
            [
                "User: What's the best restaurant near downtown?",
                "Assistant: There are several great options. What cuisine do you prefer?",
            ],
            [
                "User: I need to set up monitoring for our new microservices.",
                "Assistant: For microservices monitoring, I'd recommend Prometheus with Grafana dashboards.",
            ],
        ],
        haystack_dates=["2024/01/15 Monday 09:00", "2024/01/20 Saturday 14:00", "2024/02/01 Thursday 18:00", "2024/02/10 Saturday 11:00"],
        answer_session_ids=[1],
    ))

    items.append(BenchmarkItem(
        question_id="q_005",
        question_type="single-session-user-centric",
        question="Where is Eve planning to travel next?",
        answer="Japan in April for cherry blossom season",
        haystack_sessions=[
            [
                "User: I'm so excited about my upcoming trip to Japan!",
                "Assistant: Japan is amazing! When are you planning to go?",
                "User: I'm going in April for cherry blossom season.",
                "Assistant: April is the perfect time! Kyoto and Tokyo both have stunning cherry blossoms.",
                "User: I've already booked a ryokan in Kyoto.",
                "Assistant: Staying at a ryokan is a must-do experience. You'll love the traditional hospitality.",
            ],
            [
                "User: Can you help me practice my French?",
                "Assistant: Bien sûr! Let's start with some basic conversation.",
            ],
            [
                "User: What's a good recipe for banana bread?",
                "Assistant: Here's a classic banana bread recipe. You'll need 3 ripe bananas...",
            ],
        ],
        haystack_dates=["2024/03/01 Friday 16:00", "2024/03/05 Tuesday 10:00", "2024/03/08 Friday 14:00"],
        answer_session_ids=[0],
    ))

    # === 2. Multi-Session Reasoning (5개) ===
    items.append(BenchmarkItem(
        question_id="q_006",
        question_type="multi-session-reasoning",
        question="What programming languages does Frank use at work and for personal projects?",
        answer="Rust at work, TypeScript for personal projects",
        haystack_sessions=[
            [
                "User: At work we've been migrating our backend to Rust.",
                "Assistant: Rust is excellent for performance-critical applications. How's the migration going?",
                "User: It's challenging but the memory safety guarantees are worth it.",
                "Assistant: Absolutely. Rust's ownership model prevents many common bugs.",
            ],
            [
                "User: I've been building a side project with TypeScript and Next.js.",
                "Assistant: TypeScript with Next.js is a powerful combination. What are you building?",
                "User: It's a personal finance tracker with real-time notifications.",
                "Assistant: That's a great project idea. Are you using WebSockets for real-time features?",
            ],
            [
                "User: What's the best way to grill a steak?",
                "Assistant: For a perfect steak, start with a hot grill and season generously with salt and pepper.",
            ],
        ],
        haystack_dates=["2024/02/10 Saturday 09:00", "2024/02/15 Thursday 20:00", "2024/02/20 Tuesday 18:00"],
        answer_session_ids=[0, 1],
    ))

    items.append(BenchmarkItem(
        question_id="q_007",
        question_type="multi-session-reasoning",
        question="What are Grace's hobbies that she mentioned across conversations?",
        answer="Rock climbing and watercolor painting",
        haystack_sessions=[
            [
                "User: I went rock climbing at the gym yesterday. Made it to a V5 problem!",
                "Assistant: V5 is impressive! That requires good technique and finger strength.",
                "User: I've been climbing for about 2 years now.",
                "Assistant: Two years and already on V5 routes - you're progressing well!",
            ],
            [
                "User: Can you recommend a good book on machine learning?",
                "Assistant: 'Hands-On Machine Learning' by Aurélien Géron is excellent.",
            ],
            [
                "User: I finished a new watercolor painting today. It's a sunset landscape.",
                "Assistant: Watercolor sunsets can be stunning! The way the colors blend is beautiful.",
                "User: I've been taking classes at the community center for 6 months.",
                "Assistant: Classes are a great way to improve. Do you focus on landscapes?",
            ],
        ],
        haystack_dates=["2024/01/05 Friday 19:00", "2024/01/10 Wednesday 14:00", "2024/02/01 Thursday 17:00"],
        answer_session_ids=[0, 2],
    ))

    items.append(BenchmarkItem(
        question_id="q_008",
        question_type="multi-session-reasoning",
        question="What health-related activities does Henry do?",
        answer="Marathon running and following a plant-based diet",
        haystack_sessions=[
            [
                "User: I just signed up for the Boston Marathon next year!",
                "Assistant: The Boston Marathon! That's a prestigious race. Have you run a marathon before?",
                "User: Yes, I've completed 3 marathons. My best time is 3:15.",
                "Assistant: 3:15 is a strong time. You should be competitive at Boston.",
            ],
            [
                "User: I switched to a plant-based diet last month.",
                "Assistant: Plant-based diets can be very nutritious. Are you getting enough protein?",
                "User: I'm using a mix of legumes, tofu, and tempeh for protein.",
                "Assistant: That's a well-rounded approach. Tempeh is an excellent protein source.",
            ],
            [
                "User: What's the best way to learn Spanish?",
                "Assistant: Immersion is the most effective method. Apps like Duolingo can supplement.",
            ],
        ],
        haystack_dates=["2024/01/20 Saturday 07:00", "2024/02/05 Monday 12:00", "2024/02/15 Thursday 21:00"],
        answer_session_ids=[0, 1],
    ))

    items.append(BenchmarkItem(
        question_id="q_009",
        question_type="multi-session-reasoning",
        question="What are the two main projects Irene is working on?",
        answer="A mobile app for meditation and a blog about sustainable fashion",
        haystack_sessions=[
            [
                "User: I'm developing a mobile app for guided meditation.",
                "Assistant: Meditation apps are popular right now. What makes yours unique?",
                "User: It uses biometric feedback to customize the experience.",
                "Assistant: That's innovative! Integrating biometric data could really personalize meditation.",
            ],
            [
                "User: My blog about sustainable fashion is getting more traffic.",
                "Assistant: Sustainable fashion is a growing topic. How many readers do you have?",
                "User: About 5000 monthly visitors now. I focus on ethical brands.",
                "Assistant: 5000 monthly visitors is great! Ethical brand reviews are very valuable content.",
            ],
            [
                "User: Can you help me pick a new laptop?",
                "Assistant: Sure! What's your budget and primary use case?",
            ],
            [
                "User: I need to fix a leaky faucet.",
                "Assistant: A leaky faucet usually needs a new washer or cartridge. What type of faucet is it?",
            ],
        ],
        haystack_dates=["2024/02/01 Thursday 10:00", "2024/02/08 Thursday 15:00", "2024/02/12 Monday 11:00", "2024/02/18 Sunday 09:00"],
        answer_session_ids=[0, 1],
    ))

    items.append(BenchmarkItem(
        question_id="q_010",
        question_type="multi-session-reasoning",
        question="What musical activities is Jack involved in?",
        answer="Plays guitar in a local band and teaches music to kids on weekends",
        haystack_sessions=[
            [
                "User: Our band has a gig this Friday at the Blue Note bar.",
                "Assistant: Exciting! What kind of music does your band play?",
                "User: We play indie rock. I'm the lead guitarist.",
                "Assistant: Lead guitar in an indie rock band - that must be fun! Any original songs?",
            ],
            [
                "User: What's the difference between TCP and UDP?",
                "Assistant: TCP is connection-oriented and reliable, while UDP is connectionless and faster.",
            ],
            [
                "User: I teach music to kids every Saturday at the community center.",
                "Assistant: Teaching music to children is so rewarding. What ages do you teach?",
                "User: Ages 6-12. We focus on basic guitar and rhythm.",
                "Assistant: Starting with guitar and rhythm is perfect for that age group.",
            ],
        ],
        haystack_dates=["2024/03/01 Friday 18:00", "2024/03/05 Tuesday 10:00", "2024/03/09 Saturday 09:00"],
        answer_session_ids=[0, 2],
    ))

    # === 3. Temporal Reasoning (4개) ===
    items.append(BenchmarkItem(
        question_id="q_011",
        question_type="temporal-reasoning",
        question="What was the user doing on March 15th?",
        answer="Had a job interview at Google",
        haystack_sessions=[
            [
                "User: I have a dentist appointment tomorrow.",
                "Assistant: Good luck at the dentist! Is it just a regular checkup?",
            ],
            [
                "User: My job interview at Google is today! I'm so nervous.",
                "Assistant: Good luck! Google interviews can be challenging but rewarding. Stay confident!",
                "User: Thanks! It's for a Senior Software Engineer position.",
                "Assistant: Senior SWE at Google is a great opportunity. Focus on system design and algorithms.",
            ],
            [
                "User: I'm going grocery shopping this afternoon.",
                "Assistant: Do you have a list prepared? Planning ahead saves time at the store.",
            ],
        ],
        haystack_dates=["2024/03/14 Thursday 09:00", "2024/03/15 Friday 08:00", "2024/03/16 Saturday 14:00"],
        answer_session_ids=[1],
    ))

    items.append(BenchmarkItem(
        question_id="q_012",
        question_type="temporal-reasoning",
        question="When did the user start learning Korean?",
        answer="January 2024",
        haystack_sessions=[
            [
                "User: I just started learning Korean this month!",
                "Assistant: Exciting! Korean is a fascinating language. Have you learned Hangul yet?",
                "User: Yes, I can read the basic characters now.",
                "Assistant: Great start! Hangul is logical and can be learned quickly.",
            ],
            [
                "User: My Korean is improving. I can now order food in Korean.",
                "Assistant: Being able to order food is a great milestone! How are you practicing?",
            ],
            [
                "User: I just finished my Python project for work.",
                "Assistant: Congratulations on finishing the project! What was it about?",
            ],
        ],
        haystack_dates=["2024/01/05 Friday 20:00", "2024/02/15 Thursday 12:00", "2024/03/01 Friday 16:00"],
        answer_session_ids=[0],
    ))

    items.append(BenchmarkItem(
        question_id="q_013",
        question_type="temporal-reasoning",
        question="What happened after the user's car broke down?",
        answer="Got it towed and the mechanic found a transmission issue, then rented a car for a week",
        haystack_sessions=[
            [
                "User: My car broke down on the highway this morning!",
                "Assistant: Oh no! Are you safe? Did you call for roadside assistance?",
                "User: Yes, I'm safe. The tow truck is on its way.",
                "Assistant: Glad you're safe. Do you know what might be wrong with the car?",
            ],
            [
                "User: The mechanic says it's a transmission issue. It'll take a week to fix.",
                "Assistant: Transmission repairs can be expensive. Does your warranty cover it?",
                "User: Unfortunately not. I'll need to rent a car in the meantime.",
                "Assistant: That's frustrating. At least you'll have transportation while it's being fixed.",
            ],
            [
                "User: What's the capital of New Zealand?",
                "Assistant: The capital of New Zealand is Wellington.",
            ],
        ],
        haystack_dates=["2024/02/20 Tuesday 08:00", "2024/02/21 Wednesday 14:00", "2024/02/25 Sunday 10:00"],
        answer_session_ids=[0, 1],
    ))

    items.append(BenchmarkItem(
        question_id="q_014",
        question_type="temporal-reasoning",
        question="What was the most recent book the user finished reading?",
        answer="Project Hail Mary by Andy Weir",
        haystack_sessions=[
            [
                "User: I just finished reading Dune by Frank Herbert. Amazing book!",
                "Assistant: Dune is a sci-fi masterpiece! Did you enjoy the world-building?",
            ],
            [
                "User: I'm halfway through The Midnight Library by Matt Haig.",
                "Assistant: The Midnight Library is beautiful. The concept of parallel lives is thought-provoking.",
            ],
            [
                "User: Just finished Project Hail Mary by Andy Weir. Best book I've read this year!",
                "Assistant: Project Hail Mary is fantastic! The friendship between the characters is heartwarming.",
                "User: Rocky is such a great character.",
                "Assistant: Rocky is wonderful. Weir's ability to create an alien character you care about is remarkable.",
            ],
        ],
        haystack_dates=["2024/01/10 Wednesday 21:00", "2024/02/05 Monday 22:00", "2024/03/10 Sunday 20:00"],
        answer_session_ids=[2],
    ))

    # === 4. Knowledge Update (3개) ===
    items.append(BenchmarkItem(
        question_id="q_015",
        question_type="knowledge-update",
        question="Where does the user currently work?",
        answer="StartupXYZ (switched from MegaCorp)",
        haystack_sessions=[
            [
                "User: Work at MegaCorp has been stressful lately with the layoffs.",
                "Assistant: Layoffs can create a lot of anxiety. How are you coping?",
                "User: I'm considering looking for a new job.",
                "Assistant: It might be a good time to explore options while you're still employed.",
            ],
            [
                "User: I got a job offer from StartupXYZ!",
                "Assistant: Congratulations! That's exciting. What role is it for?",
                "User: Same role but with equity and a more innovative culture.",
                "Assistant: Equity in a startup can be very valuable. The culture change could be refreshing too.",
            ],
            [
                "User: I started at StartupXYZ last week. The team is amazing!",
                "Assistant: Glad to hear you're enjoying the new job! How's the onboarding process?",
                "User: Very smooth. They have great documentation and mentoring.",
                "Assistant: Good onboarding makes such a difference. Sounds like you made the right choice!",
            ],
        ],
        haystack_dates=["2024/01/15 Monday 17:00", "2024/02/01 Thursday 10:00", "2024/02/20 Tuesday 09:00"],
        answer_session_ids=[2],
    ))

    items.append(BenchmarkItem(
        question_id="q_016",
        question_type="knowledge-update",
        question="What database does the user's team currently use?",
        answer="PostgreSQL (migrated from MongoDB)",
        haystack_sessions=[
            [
                "User: We're having scaling issues with our MongoDB cluster.",
                "Assistant: MongoDB scaling can be tricky. Have you considered sharding?",
                "User: We've tried, but our query patterns don't work well with it.",
                "Assistant: If your queries need complex joins, a relational database might be better suited.",
            ],
            [
                "User: We decided to migrate from MongoDB to PostgreSQL.",
                "Assistant: PostgreSQL is excellent for complex queries. How are you planning the migration?",
                "User: We'll do it gradually, starting with the user service.",
                "Assistant: Gradual migration is the safest approach. Start with less critical services first.",
            ],
            [
                "User: The PostgreSQL migration is complete! Performance improved by 40%.",
                "Assistant: 40% improvement is significant! PostgreSQL's query optimizer is very efficient.",
            ],
        ],
        haystack_dates=["2024/01/10 Wednesday 11:00", "2024/01/25 Thursday 14:00", "2024/02/15 Thursday 16:00"],
        answer_session_ids=[2],
    ))

    items.append(BenchmarkItem(
        question_id="q_017",
        question_type="knowledge-update",
        question="What city does the user live in now?",
        answer="Austin (moved from Seattle)",
        haystack_sessions=[
            [
                "User: The rain in Seattle is really getting to me.",
                "Assistant: Seattle's rainy season can be tough. Have you tried light therapy?",
            ],
            [
                "User: I'm seriously thinking about moving to Austin, Texas.",
                "Assistant: Austin has great weather and a growing tech scene. What's drawing you there?",
                "User: The sunshine, lower cost of living, and my company has an office there.",
                "Assistant: Those are all compelling reasons. Austin's food scene is amazing too!",
            ],
            [
                "User: I just moved to Austin last week! The weather is incredible.",
                "Assistant: Welcome to Austin! The weather is definitely a big change from Seattle.",
                "User: Already found a great BBQ place near my apartment.",
                "Assistant: Austin BBQ is legendary. You'll never run out of places to try!",
            ],
        ],
        haystack_dates=["2024/01/05 Friday 15:00", "2024/01/20 Saturday 11:00", "2024/02/10 Saturday 13:00"],
        answer_session_ids=[2],
    ))

    # === 5. Abstention (3개) ===
    items.append(BenchmarkItem(
        question_id="q_018",
        question_type="single-session-user-centric_abs",
        question="What is the user's blood type?",
        answer="ABSTAIN - information not available",
        haystack_sessions=[
            [
                "User: I had a regular checkup at the doctor today.",
                "Assistant: How did it go? Everything looking good?",
                "User: Yes, all my vitals are normal. Blood pressure is 120/80.",
                "Assistant: 120/80 is a perfect blood pressure reading. Great news!",
            ],
            [
                "User: I need to schedule a flu shot.",
                "Assistant: Flu shots are typically available at pharmacies and clinics starting in September.",
            ],
        ],
        haystack_dates=["2024/03/01 Friday 16:00", "2024/03/10 Sunday 10:00"],
        answer_session_ids=[],
    ))

    items.append(BenchmarkItem(
        question_id="q_019",
        question_type="multi-session-reasoning_abs",
        question="What is the user's salary?",
        answer="ABSTAIN - information not available",
        haystack_sessions=[
            [
                "User: I got a promotion at work today!",
                "Assistant: Congratulations on the promotion! What's your new title?",
                "User: I'm now a Team Lead in the engineering department.",
                "Assistant: Team Lead is a great step in your career. Will you be managing a team?",
            ],
            [
                "User: I'm thinking about buying a new house.",
                "Assistant: Exciting! What area are you looking in?",
                "User: Somewhere in the suburbs with a good school district.",
                "Assistant: Good school districts are important for long-term value too.",
            ],
        ],
        haystack_dates=["2024/02/01 Thursday 17:00", "2024/02/15 Thursday 20:00"],
        answer_session_ids=[],
    ))

    items.append(BenchmarkItem(
        question_id="q_020",
        question_type="temporal-reasoning_abs",
        question="What did the user do on December 25th, 2023?",
        answer="ABSTAIN - information not available in the conversations",
        haystack_sessions=[
            [
                "User: Happy New Year! My resolution is to exercise more.",
                "Assistant: Happy New Year! That's a great resolution. Do you have a specific plan?",
            ],
            [
                "User: I went skiing last weekend. The snow was perfect.",
                "Assistant: Sounds like a great weekend! Where did you go skiing?",
                "User: We went to Aspen. First time there.",
                "Assistant: Aspen is world-class! How were the slopes?",
            ],
        ],
        haystack_dates=["2024/01/01 Monday 10:00", "2024/01/08 Monday 19:00"],
        answer_session_ids=[],
    ))

    return items


async def run_retrieval_benchmark() -> None:
    """검색 품질 벤치마크 실행"""
    db_path = str(Path(__file__).parent / "data" / "bench_retrieval.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # 기존 DB 삭제
    if os.path.exists(db_path):
        os.remove(db_path)

    storage = DirectStorageBackend(db_path)
    await storage.initialize()

    # sqlite-vec가 없으면 fuzzy search로 폴백
    vec_available = _sqlite_vec_available()
    if not vec_available:
        logger.warning("sqlite-vec not available, using fuzzy search fallback")
        _patch_search_for_fuzzy(storage)

    search_mode = "hybrid" if vec_available else "fuzzy"
    print(f"  Search mode: {search_mode} (sqlite-vec: {'enabled' if vec_available else 'disabled'})\n")

    try:
        items = build_mock_dataset()
        indexer = create_indexer(strategy="session", include_date=True)
        retriever = Retriever(storage=storage, top_k=10, search_mode=search_mode)

        results: List[QuestionResult] = []
        total_start = time.time()

        for item in items:
            project_id = f"lme-{item.question_id}"

            # 1. INDEX
            num_indexed = await indexer.index(storage, item, project_id)

            # 2. RETRIEVE
            search_results, retrieved_sids, metrics = await retriever.retrieve(
                query=item.question,
                project_id=project_id,
                answer_session_ids=item.answer_session_ids,
            )

            # 기권 유형 처리: answer_session_ids가 비어있으면 검색 결과 없는 것이 정답
            if not item.answer_session_ids:
                # 검색 결과가 없거나 관련 없으면 정답
                eval_label = 1 if not retrieved_sids else 0
            else:
                # recall_any@10 > 0 이면 "정답 세션을 찾았다"
                eval_label = 1 if metrics.recall_any.get(10, 0) > 0 else 0

            result = QuestionResult(
                question_id=item.question_id,
                question_type=item.question_type,
                question=item.question,
                answer=item.answer,
                hypothesis=f"[retrieval-only] retrieved sessions: {retrieved_sids}",
                retrieved_session_ids=retrieved_sids,
                retrieval_metrics=metrics,
                eval_label=eval_label,
            )
            results.append(result)

            # 3. CLEANUP
            params = SearchParams(query="", project_id=project_id, limit=20)
            while True:
                resp = await storage.search_memories(params)
                if not resp.results:
                    break
                for r in resp.results:
                    await storage.delete_memory(r.id)

        total_elapsed = time.time() - total_start

        # 리포트 생성
        report = generate_report(
            results=results,
            experiment_name="mem-mesh retrieval benchmark (mock data)",
            language="en",
            indexing_strategy="session",
            config_summary={
                "top_k": "10",
                "search_mode": "hybrid",
                "questions": str(len(items)),
                "total_time": f"{total_elapsed:.1f}s",
            },
        )
        print_report(report)

        # 상세 결과
        print("\n--- Per-Question Details ---")
        print(f"{'ID':<8} {'Type':<35} {'R_any@10':>9} {'R_all@10':>9} {'Sessions':>10} {'Time(ms)':>9}")
        print("-" * 85)
        for r in results:
            ra10 = r.retrieval_metrics.recall_any.get(10, 0)
            rall10 = r.retrieval_metrics.recall_all.get(10, 0)
            t = r.retrieval_metrics.retrieval_time_ms
            print(
                f"{r.question_id:<8} {r.question_type:<35} "
                f"{ra10:>8.1%} {rall10:>8.1%} "
                f"{str(r.retrieved_session_ids):>10} {t:>8.1f}"
            )

    finally:
        await storage.shutdown()
        # 임시 DB 정리
        if os.path.exists(db_path):
            os.remove(db_path)


if __name__ == "__main__":
    asyncio.run(run_retrieval_benchmark())
