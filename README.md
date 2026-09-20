Sentinel

An operating-system-inspired scheduler for hospital alert prioritization.

Sentinel is a full-stack hospital operations simulator that explores a simple idea:

What if hospital alerts were scheduled like processes in an operating system?

Instead of allocating CPU time to processes, Sentinel allocates limited nursing attention to incoming clinical events.

Note: Sentinel is an educational hackathon prototype built with synthetic data. It is not intended for real-world clinical decision-making.

Inspiration

As a pre-med student, I have spent considerable time in hospitals, especially emergency rooms. One thing I noticed was that available resources sometimes could not keep up with patient volume.

This week in my Operating Systems class, we learned about process scheduling. That inspired me to build an operating-system-style scheduler for hospital alerts.

What It Does

Sentinel has two main modes:

Manual Mode — users can manually assign nurses to incoming incidents.

Sentinel Mode — the scheduler suggests severity based on synthetic vitals and automatically prioritizes work for available nurses.

The Simulation tab compares Sentinel against a traditional FIFO (First-In, First-Out) scheduler under the same synthetic workload.

How It Works

The backend is written in Python using FastAPI.

The core of the project is a custom scheduler that handles:

Severity-based prioritization

Nurse assignment

Duplicate alert consolidation

Aging to prevent starvation

Clinical deterioration over time

The synthetic workload includes randomly generated vitals, duplicate/noisy alerts, variable service times, and deterioration when incidents wait too long.

The frontend is built with:

HTML

CSS

JavaScript

Persistent data is stored with Supabase, and the application is deployed on Render.

Tech Stack

Backend: Python, FastAPI

Frontend: HTML, CSS, JavaScript

Database: Supabase

Deployment: Render

Scheduler Design

The first version used a greedy strategy that always prioritized the most severe available incident.

That created a problem: lower-priority incidents could wait indefinitely.

To address this, Sentinel adds aging, which increases priority when an incident waits too long. Sentinel also consolidates duplicate alerts so repeated signals do not unnecessarily consume nursing attention.

Project Structure

Sentinel/
├── backend/
│   ├── app/
│   ├── tests/
│   ├── supabase/
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── product.html
│   ├── app.js
│   ├── product.js
│   └── style.css
├── README.md
└── .gitignore

Running Locally

git clone https://github.com/rycho65/Sentinel.git
cd Sentinel
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload

Configure your Supabase environment variables before starting the app.

Challenges

The biggest challenge was designing the scheduler itself.

I initially used a greedy algorithm, but lower-priority incidents waited too long. I then added aging to prevent starvation and duplicate consolidation to handle repeated/noisy alerts.

A large part of the project involved learning scheduling concepts while implementing them.

What I Learned

This project helped me learn about:

Greedy algorithms

Priority scheduling

FIFO scheduling

Starvation

Aging

FastAPI

REST APIs

Full-stack development

Databases

Deployment

Future Work

If I had more time, I would add individual nurse accounts so each nurse could see their own assignments instead of only the manager-facing dashboard.

Other possible additions include:

Multiple hospital units

Nurse specialization

Shift changes

More realistic workload distributions

Historical analytics

Individual Contribution

Sentinel was built as a solo project.
