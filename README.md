# DebateSim

<div align="center">

### Learn to think critically by debating an AI that talks back.

**DebateSim is an AI-powered debate coach and civic-learning platform that gives every learner an opponent, a coach, and a judge—on demand.**

[Try the live app](https://debatesim.us) · [View the source code](https://github.com/alexliao95311/PromethusAIChallenge) · **[2-minute demo video — add link before submission](#two-minute-demo-plan)**

</div>

---

## The problem

Debate builds research, communication, media literacy, and critical-thinking skills, but meaningful practice is difficult to access. A learner usually needs a partner, a coach, a judge, a shared schedule, and enough subject knowledge to begin. Feedback may arrive long after a speech, and students often practice only the side they already understand.

Civic topics add another barrier: bills and ballot measures are long, technical, and intimidating. Students cannot debate policy well if they cannot first understand what the policy does.

DebateSim removes those barriers. A learner can choose a topic, take either side, speak or type an argument, receive a contextual AI response, and get immediate, speech-specific coaching. They can also explore real legislation, turn it into understandable analysis, and use it as the subject of a structured debate.

## What DebateSim teaches

- **Argument construction:** turn claims into supported reasoning with warrants and impacts.
- **Rebuttal and listening:** respond to the argument that was actually made instead of repeating a prepared case.
- **Strategic communication:** prioritize, compare impacts, remove filler, and make limited speaking time count.
- **Perspective-taking:** practice both affirmative and negative positions against varied AI opponents.
- **Civic literacy:** break down federal bills, state bills, and California propositions into understandable dimensions.
- **Reflection:** review transcripts, round-specific feedback, judge decisions, and concrete rewrites.

The central learning loop is simple:

```text
Choose a topic and side
        ↓
Make an argument by voice or text
        ↓
AI opponent generates a contextual response
        ↓
AI coach diagnoses the specific speech
        ↓
Revise, rebut, and continue
        ↓
AI judge explains the result and next steps
```

## How it works

### 1. Deliberate practice with the Debate Trainer

The trainer follows a Public Forum progression—Constructive, Rebuttal, Summary, and Final Focus—rather than returning generic writing advice. Its coaching changes with the purpose of each speech:

- Constructives are checked for case structure, evidence, warrants, internal links, and impacts.
- Rebuttals are checked for direct clash, coverage, refutation, and evidence comparison.
- Summaries are checked for strategic collapse, extensions, frontlines, and weighing.
- Final Focus speeches are checked for crystallization, voters, comparative weighing, and consistency.

Feedback identifies exact inefficient passages, recommends cuts or shorter rewrites, estimates words saved, and gives actionable improvements. This lets students apply advice in the next speech—not someday after the round is over.

### 2. An always-available AI opponent

Learners can practice **AI vs User**, observe **AI vs AI**, or run **User vs User** debates. The AI receives the topic, side, debate format, speech context, and prior transcript so its next response engages with the evolving round. Supported formats include standard debate, Public Forum, and Lincoln-Douglas.

### 3. Explainable AI judging

At the end of a debate, a separate judging chain evaluates the complete transcript and provides a decision with reasoning and improvement feedback. Separating the opponent, coach, and judge roles keeps each AI task focused and turns a debate into a complete practice-and-reflection cycle.

### 4. Real policy as learning material

Students can search and analyze current federal legislation through Congress.gov, state legislation through LegiScan, California ballot propositions, or an uploaded document. DebateSim can extract long bill text and analyze it across six lenses:

1. Economic impact
2. Public benefit
3. Implementation feasibility
4. Constitutional concerns
5. Political viability
6. Democratic impact

This bridges “learning about government” and actually reasoning about policy. After understanding a measure, the learner can debate its tradeoffs from more than one perspective.

### 5. Accessible, reusable practice

- Voice input supports learners who communicate better by speaking than typing.
- Text-to-speech can read AI responses aloud.
- English and Chinese preferences are supported in the training experience.
- Firebase authentication and Firestore-backed history preserve debates for later reflection.
- Transcripts can be shared through read-only links or exported as PDFs with judge feedback.
- Guest access lowers the barrier to trying the platform.

## Why AI is essential—not an add-on

A static lesson can explain what a rebuttal is, but it cannot listen to a new argument, challenge its assumptions, adapt the next speech, and point to the learner's exact wording. DebateSim uses language models at every stage of that interaction:

| AI role | Input | Educational output |
|---|---|---|
| Opponent | Topic, side, format, persona, and debate history | A context-aware argument or rebuttal that forces the learner to adapt |
| Coach | Student speech, round, speech type, and language | Targeted diagnosis, precise cuts, rewrites, and next-step improvements |
| Judge | Full transcript and debate context | An explainable decision and holistic performance feedback |
| Policy analyst | Bill text or selected sections | A structured, multi-dimensional explanation of complex legislation |

DebateSim routes requests through OpenRouter and supports models from multiple providers. Purpose-built LangChain prompt chains constrain each model to its educational role, while fallback models and request handling improve reliability. AI is not used to complete the learning task for the student; it creates the responsive practice environment in which the student performs the task.

## Competition rubric alignment

### Educational Impact — 25 points

**Real problem:** high-quality debate practice depends on scarce people, time, and expertise, while complex civic material is difficult for new learners to enter.

**Our response:** DebateSim makes structured practice available at any time, provides feedback after each student speech, encourages learners to confront opposing viewpoints, and connects argument skills to authentic legislation. The tool supports a repeatable cycle of attempt, feedback, revision, and reflection rather than passive content consumption.

### Creative Use of AI/ML — 25 points

AI performs four distinct, coordinated educational roles: opponent, coach, judge, and legislative analyst. Prompts adapt to format and round type; responses use the accumulated debate context; coaching quotes and rewrites the learner's own language; and different models can be selected or used as fallbacks. Without AI, the personalized interaction at the center of DebateSim would not exist.

### Technical Education / Execution — 25 points

The project is a working full-stack application with a React/Vite interface, FastAPI backend, modular AI chains, Firebase authentication and persistence, external legislative-data integrations, PDF text extraction, voice input/output, caching, error handling, and automated backend tests. Guided setup screens, clear round labels, live loading states, transcript navigation, history, sharing, and export are designed to keep the experience understandable from first argument to final feedback.

### Pitch & Demo — 25 points

The two-minute demo below is organized around one learner story: a student who needs practice, receives immediate personalized coaching, and applies those skills to a real civic issue. It shows the problem, the core AI learning loop, the technical differentiator, and the educational outcome without turning the pitch into a feature list.

## Two-minute demo plan

> **Submission video:** Add the final public video URL here before submitting.

| Time | Screen | Narration goal |
|---|---|---|
| 0:00–0:15 | Title, then a quick view of the trainer | “Debate is one of the best ways to learn critical thinking—but practice normally requires an opponent, coach, and judge. DebateSim gives every student all three.” |
| 0:15–0:35 | Select AI vs User, Public Forum, a topic, and a side | Show that a complete practice session can begin in seconds and that the learner controls the position they practice. |
| 0:35–1:00 | Speak or type a short student argument; show the AI rebuttal | Explain that the opponent uses the topic, format, side, round, and conversation history to respond to this learner—not to a canned exercise. |
| 1:00–1:20 | Open the speech feedback panel; highlight an exact cut/rewrite | Show how feedback changes by speech type and can be used immediately in the next round. |
| 1:20–1:38 | Show final judging and transcript/history | Complete the learning loop: perform, receive an explainable evaluation, reflect, and practice again. |
| 1:38–1:52 | Search or open a real bill; show the six-part analysis | Connect debate skill to civic understanding and authentic source material. |
| 1:52–2:00 | Architecture graphic or model selector, then URL and repository | “AI is the opponent, coach, judge, and policy analyst at the core of DebateSim. Try it at debatesim.us.” |

Recording tip: preload the topic and bill, use a short prepared speech, and record completed AI responses so network latency does not consume demo time.

## Architecture

```text
React 18 + Vite
  ├── Debate setup, trainer, transcript, judge, legislation, history
  ├── Browser speech recognition and text-to-speech controls
  └── Firebase Auth / Firestore
                │ HTTPS / JSON
                ▼
FastAPI
  ├── Debater chain ───────┐
  ├── Trainer chain ───────┼── OpenRouter ── multiple LLM providers
  ├── Judge chain ─────────┘
  ├── PDF/text extraction
  ├── Congress.gov, LegiScan, and CA proposition services
  └── TTL caching and fallback handling
```

### Technology stack

- **Frontend:** React 18, Vite, React Router, Axios, Bootstrap, Firebase, jsPDF/html2pdf.js
- **Backend:** Python, FastAPI, Pydantic, LangChain, OpenAI-compatible OpenRouter client
- **AI/ML:** multi-model LLM orchestration, task-specific prompt chains, sentence-transformer support, fuzzy search
- **Data and media:** Congress.gov, LegiScan, California propositions, PDFMiner/pdfplumber, Web Speech API, Google Cloud TTS
- **Quality:** Pytest, ESLint, typed request models, CORS configuration, caching, async endpoints

## Run locally

### Prerequisites

- Python 3.9+
- Node.js 18+
- An [OpenRouter](https://openrouter.ai/) API key
- A Firebase web project for authentication
- Optional: Congress.gov, LegiScan, and Google Cloud credentials for their respective features

### 1. Backend

```bash
git clone https://github.com/alexliao95311/PromethusAIChallenge.git
cd PromethusAIChallenge

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add at least `OPENROUTER_API_KEY` to `.env`, then start the API:

```bash
python main.py
```

The backend runs at `http://localhost:8000`.

### 2. Frontend

Create `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
VITE_FIREBASE_API_KEY=your_value
VITE_FIREBASE_AUTH_DOMAIN=your_value
VITE_FIREBASE_PROJECT_ID=your_value
VITE_FIREBASE_STORAGE_BUCKET=your_value
VITE_FIREBASE_MESSAGING_SENDER_ID=your_value
VITE_FIREBASE_APP_ID=your_value
VITE_FIREBASE_MEASUREMENT_ID=your_value
```

Then install and run the client:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### Optional service keys

Set these in the root `.env` only when using the related feature:

```env
CONGRESS_API_KEY=your_value
LEGISCAN_API_KEY=your_value
GOOGLE_CLOUD_PROJECT_ID=your_value
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
BACKEND_ORIGINS=http://localhost:5173
```

Never commit `.env` files or service-account credentials.

## Test and build

```bash
# Backend model and repository tests
python -m pytest tests -v

# Frontend quality checks
cd frontend
npm run lint
npm run build
```

## Repository guide

```text
DebateSim/
├── main.py                     # FastAPI application and API endpoints
├── chains/
│   ├── debater_chain.py        # Contextual AI opponent
│   ├── trainer_chain.py        # Round- and speech-specific coaching
│   └── judge_chain.py          # Debate evaluation
├── billsearch.py               # Congress.gov discovery
├── legiscan_service.py         # State legislation
├── ca_propositions_service.py  # California ballot measures
├── speech_utils/               # Speech and voice services
├── models/ and services/       # Data models and persistence layer
├── frontend/src/               # React application
├── tests/                      # Backend tests and Firestore fake
└── docs/                       # Architecture, APIs, setup, and reports
```

For deeper technical detail, see the [project report](docs/PROJECT_REPORT.md), [API reference](docs/API_REFERENCE.md), and [documentation hub](docs/README.md).

## Responsible use and limitations

DebateSim is a practice and learning tool. AI responses can contain errors, invented claims, or bias, and a confident argument is not necessarily a factual one. Legislative analyses are educational summaries, not legal advice. Learners should verify important claims against primary sources, and educators should treat AI judging as formative feedback rather than an authoritative tournament ballot.

The platform keeps the learner in control: users choose the topic and side, contribute their own speeches, can inspect the complete transcript, and decide whether to accept or reject the AI's feedback.

## Submission checklist

- [x] Functional educational AI application
- [x] Public source-code repository
- [x] Live application
- [ ] Add the final public two-minute demo video link to this README
- [ ] Verify all links and demo credentials in a clean browser session
- [ ] Record using the timed plan above and keep the final cut at or under two minutes

## License

Released under the [MIT License](LICENSE).

---

<div align="center">

**DebateSim turns AI from an answer machine into a practice partner.**

</div>
