Sentinel

An operating-system-inspired scheduler for hospital alert prioritization.

Sentinel is a full-stack hospital operations simulator that explores a simple question:

What if hospital alerts were scheduled like processes in an operating system?

Instead of allocating CPU time to processes, Sentinel allocates limited nursing attention to incoming clinical events.

Overview

Sentinel models a hospital environment with:

incoming clinical alerts

limited nursing resources

dynamic patient severity

duplicate/noisy events

queueing and prioritization

starvation prevention through aging

It also includes a simulation environment that compares Sentinel's scheduling strategy against a traditional FIFO (First-In, First-Out) scheduler under the same synthetic workload.

Disclaimer: Sentinel is an educational hackathon prototype built using synthetic data. It is not intended for real-world clinical decision-making.

Inspiration

As a pre-med student, I have spent considerable time in hospitals, especially emergency rooms. One thing I noticed was that available resources sometimes could not keep up with patient volume.

This week in my Operating Systems class, we learned about process schedulers. That led to the idea behind Sentinel:

Could operating-system scheduling concepts be applied to hospital attention management?

Features

Live Product

Sentinel supports two operating modes:

Mode

Description

Manual Mode

Users manually assign nurses to incoming incidents.

Sentinel Mode

Sentinel suggests severity from synthetic vitals and intelligently prioritizes available work.

The dashboard displays information such as:

room status

nurse availability

active incidents

queue state

completed incidents

suggested severity

escalation behavior

Simulation

The simulation tab compares:

Sentinel Scheduler
vs.
Traditional FIFO Scheduler

Both systems receive the same synthetic workload so their behavior can be compared directly.

Simulation controls include:

number of rooms

number of nurses

shift length

incoming pings per hour

workload scenario

playback speed

Available scenarios:

Slow Day

Normal

Rush

Scheduler Design

The first version of Sentinel used a simple greedy strategy:

Always process the highest-severity available incident first.

That worked well for critical incidents, but it created a major problem:

Lower-priority incidents could wait indefinitely.

This is the classic scheduling problem of starvation.

To address it, Sentinel adds several mechanisms.

Severity-Based Priority

Higher-severity incidents are prioritized over lower-severity incidents.

Aging

If an incident waits too long, its priority increases.

Initial severity
      ↓
Waits too long
      ↓
Priority increases
      ↓
Eventually receives attention

This prevents lower-priority incidents from being permanently ignored.

Duplicate Consolidation

Synthetic monitoring events can contain repeated alerts for the same underlying issue.

Rather than treating every duplicate alert as an independent job, Sentinel consolidates them into a single incident.

Clinical Deterioration

Some synthetic patients worsen when left unattended.

Green → Yellow → Orange → Red

This creates a dynamic scheduling environment rather than a static queue.

Synthetic Data

Sentinel does not use real patient data.

The simulator generates synthetic events with:

randomized vital signs

severity levels

variable nurse-service times

duplicate alerts

false/noisy alerts

deterioration over time

rare long-duration edge cases

Each priority group has an expected amount of nurse time, while a small percentage of cases take abnormally long to simulate unpredictable workloads.

Tech Stack

Layer

Technology

Backend

Python, FastAPI

Frontend

HTML, CSS, JavaScript

Database

Supabase

Deployment

Render

Core Logic

Custom scheduler + simulation engine

Architecture

┌──────────────────────────────┐
│           Frontend           │
│      HTML / CSS / JS         │
└──────────────┬───────────────┘
               │
           HTTP / API
               │
┌──────────────▼───────────────┐
│           FastAPI            │
│        Python Backend        │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│      Sentinel Scheduler      │
│                              │
│  • Severity prioritization   │
│  • Aging                     │
│  • Duplicate consolidation   │
│  • Nurse assignment          │
│  • Clinical deterioration    │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│           Supabase           │
│       Persistent Storage     │
└──────────────────────────────┘

Project Structure

Sentinel/
├── backend/
│   ├── app/
│   ├── tests/
│   ├── supabase/
│   └── requirements.txt
│
├── frontend/
│   ├── index.html
│   ├── product.html
│   ├── app.js
│   ├── product.js
│   └── style.css
│
├── README.md
└── .gitignore

Running Locally

1. Clone the repository

git clone https://github.com/rycho65/Sentinel.git
cd Sentinel

2. Install backend dependencies

pip install -r backend/requirements.txt

3. Configure environment variables

Create your local environment file and add the required Supabase credentials.

Example:

SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

Do not commit your .env file.

4. Start the application

uvicorn app.main:app --app-dir backend --reload

Then open the local URL shown by Uvicorn, typically:

http://127.0.0.1:8000

Challenges

Preventing Starvation

My original greedy approach favored high-severity incidents too aggressively.

Lower-priority patients could wait for far too long, so I added aging to progressively increase their priority.

Handling Alert Noise

The synthetic workload also contains duplicate and noisy events.

Sentinel consolidates repeated alerts before they unnecessarily consume nursing attention.

Learning While Building

I had only recently learned about operating-system schedulers before starting this project, so a large portion of the build involved learning concepts while implementing them.

Topics I had to learn or apply included:

greedy algorithms

priority scheduling

FIFO scheduling

starvation

aging

process-like state representation

simulation design

What I'm Proud Of

The scheduler is the core accomplishment of the project.

What began as a simple greedy algorithm evolved into a system that handles:

priority

constrained resources

starvation

aging

duplicate events

deterioration

variable service times

I was also able to turn the scheduler into a complete interactive full-stack web application and deploy it.

What I Learned

Sentinel helped me connect concepts from operating systems, algorithms, and full-stack development.

I gained hands-on experience with:

scheduling algorithms

backend development

REST APIs

FastAPI

frontend development

JavaScript

databases

deployment

simulation design

full-stack application architecture

Future Work

The current application primarily shows the manager / operations view.

A future version could give each nurse an individual sign-in and dashboard showing:

assigned incidents

room

severity

current workload

assignment notifications

incident completion controls

Other possible extensions include:

multiple hospital units

nurse specialization

shift changes

additional scheduling strategies

more realistic workload distributions

historical analytics

Individual Contribution

Sentinel was built as a solo project.

I designed and implemented the scheduler, simulation environment, backend, frontend, database integration, and deployment.
