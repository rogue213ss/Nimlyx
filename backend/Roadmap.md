🚀 Nimlyx Roadmap

Analyze. Explore. Discover.

Nimlyx helps gamers understand what games are worth their time, money, and hardware.

Version 1.0 — Steam Intelligence Platform
Phase 1 — Complete Core Game Experience 🔨 CURRENT
🎮 Game Detail Page
 Hero section
 Quick facts
 Reviews analysis
 Nimlyx Score
 Developer / publisher
 Similar games foundation
 Screenshots system
 Trailer/media system
 App ID-based routing
 Search → Game Page flow
 Discover → Game Page flow
 Final UI polish
 Final responsive/mobile polish
 Final QA
📱 Mobile Experience
 Mobile-specific styling
 Mobile search experience
 Mobile game page foundation
 Final header/mobile navigation polish
 Media controls polish
 Final mobile QA
Phase 2 — Nimlyx PC Compatibility ⭐

Goal:

Before buying a game, users should know whether their PC can run it.

🖥️ Hardware Intelligence
Hardware Dataset

Nimlyx V1 hardware dataset:

64 devices

44 GPUs
20 CPUs
GPU Database

Includes:

NVIDIA
GT series
GTX series
RTX series
Older and newer generations
AMD
HD series
R7/R9
RX 400/500
Vega
RX 5000
RX 6000
RX 7000
Integrated Graphics
Intel HD
Intel UHD
Intel Iris
AMD integrated graphics
CPU Database

Includes representative:

Intel
Older Core generations
Core i3/i5/i7/i9
Xeon where relevant
AMD
FX
Athlon
Ryzen
📊 Hardware Data Pipeline
 Hardware schema defined
 Source strategy defined
 TechPowerUp removed from V1 pipeline
 Alternative authoritative sources selected
 64-device dataset scope defined
 Complete hardware_sources.json
 Validate all 64 devices
 Integrate hardware data into backend/database
 Final data QA
🧮 Hardware Ranking System

Nimlyx will use a specification-derived ranking system, not benchmark data.

CPU Ranking

Outputs:

 single_thread_score
 multi_thread_score
 performance_score
 efficiency_score

Methodology:

 Finalize SMT factor
 Finalize CPU score formulas
 Implement geometric-mean overall score
 Handle missing boost clocks
 Handle missing TDP
 Document score limitations
 Validate same-generation ordering
 Validate deterministic/stable scoring
GPU Ranking

Outputs:

 compute_capability_score
 category_score
 efficiency_score

Methodology:

 Finalize shader/clock vs bandwidth weighting
 Finalize memory-type transfer-rate table
 Derive memory bandwidth consistently
 Handle missing TDP
 Handle missing GPU fields
 Document cross-vendor limitations
 Validate same-generation ordering
 Validate Consumer / Professional / Integrated handling
Ranking Methodology Validation
 Review Claude's v3 methodology
 Approve final constants/weights
 Confirm no architecture-performance multiplier
 Confirm no benchmark-derived inputs
 Confirm no TDP contribution to raw performance
 Confirm VRAM remains a capability attribute, not a performance multiplier
 Confirm percentile is validation/display-only
 Run relative-order assertions
 Run missing-data tests
 Run duplicate-ID tests
 Run deterministic-output tests
 Run score-stability tests
 Final ranking methodology sign-off

Important: The methodology is currently proposed only. No ranking implementation or hardware data modification should happen until the methodology is approved.

⚙️ Compatibility Engine

Input:

CPU
GPU
RAM

Compare against:

Minimum Requirements
Recommended Requirements

Output:

🟢 Runs Well
CPU: Good
GPU: Good
RAM: Good


Recommended:
1080p Medium / High
🟡 Playable
GPU: Below recommended


Suggested:
Lower graphics settings
🔴 Not Recommended
GPU does not meet minimum requirements
Compatibility Features
 Minimum requirement parser
 Recommended requirement parser
 CPU comparison
 GPU comparison
 RAM comparison
 Performance tier calculation
 Compatibility score
 User hardware input
 Results UI
 Game-page compatibility section
 Edge-case handling
 QA across hardware combinations
Phase 3 — Nimlyx Core Pages & Trust Layer

Before expanding discovery, finish the pages that make Nimlyx feel like a complete product.

Informational Pages
 About Nimlyx
 How Nimlyx Works
 Hardware / Compatibility explanation
 Data Sources
 Contact
 FAQ
Legal / Privacy
 Privacy Policy
 Terms of Service
 Cookie Policy
 Cookie consent system
 Third-party/API disclosure
Product Polish
 Global footer
 Navigation consistency
 Loading states
 Error states
 Empty states
 404 page
 Accessibility pass
 SEO metadata
 Final responsive QA
Phase 4 — Homepage Discovery Engine 🔥

Goal:

Users should be able to discover great games without searching.

🔥 Trending Right Now

"What is everyone playing?"

💎 Hidden Gems

"What deserves more attention?"

💸 Best Deals

"What's actually worth buying?"

🖥️ Low-End Legends

"Great games for weaker PCs."

📈 Turning Around

"Games getting better."

😡 Most Controversial

"Players can't agree."

🏆 Highest Nimlyx Score

"The safest recommendations."

🆕 Fresh Releases

"What's new?"

Discovery Intelligence
 Define ranking logic
 Define data requirements
 Build recommendation queries
 Prevent duplicate games across sections
 Add refresh/update strategy
 Finalize homepage layout
Version 1.5 — Collection Pages

Turn discovery sections into dedicated experiences.

Examples:

/collections/hidden-gems
/collections/low-end-legends
/collections/best-deals
/collections/trending
/collections/highest-rated

Features:

 100+ games per collection where appropriate
 Sorting
 Filters
 Pagination
 Collection-specific ranking
 Explanations for why games appear
 Compatibility filtering
 Search within collections
Version 2.0 — Personal Nimlyx 👤

Goal:

Make Nimlyx understand the individual gamer.

Steam Integration
 Steam login
 Import Steam library
 Analyze owned games
 Playtime analysis
 Backlog analysis
 Recently played analysis
 Forgotten games detection
Personal Recommendations

Combine:

Steam Library
+
Play History
+
Nimlyx Score
+
Hardware
+
Game Preferences
Version 2.5 — Community Layer 👥

Optional expansion.

 User accounts
 User profiles
 User collections
 Ratings
 Reviews
 Favorite games
 Public lists
 Community recommendations
Version 3.0 — Nimlyx AI 🤖

Goal:

Turn Nimlyx into an intelligent gaming assistant.

Examples:

"Recommend a game like Witcher 3 but shorter."

"Find me a co-op game under $10."

"Can my PC run Cyberpunk?"

"I have 20 hours this weekend. What should I play?"

AI can use:

Nimlyx Score
+
Steam data
+
Hardware database
+
Compatibility engine
+
User library
+
User history
+
Collection data
🧭 Updated Current Execution Order
Sprint 5 — Core Completion 🔨
 Finish similar games
 Finish media polish
 Add system requirements section
 Complete mobile/header polish
 Finalize Game Detail Page
 Begin compatibility UI foundation
Sprint 6 — Hardware Dataset & Methodology 🧠
Dataset
 Complete 44 GPU dataset
 Complete 20 CPU dataset
 Generate/validate hardware_sources.json
 Final hardware data QA
Ranking Methodology
 Review Claude v3 methodology
 Approve SMT factor
 Approve GPU shader/clock/bandwidth weighting
 Approve memory transfer-rate table
 Confirm CPU geometric-mean aggregation
 Finalize methodology documentation
 Sign off on ranking model

No scoring implementation before methodology sign-off.

Sprint 7 — Hardware Ranking & Compatibility Engine ⚙️
Hardware Integration
 Integrate hardware database
 Implement CPU ranking
 Implement GPU ranking
 Implement efficiency calculations
 Implement missing-data handling
 Generate ranking output
 Run ranking validation suite
Compatibility
 Build requirement normalization
 Build CPU comparison
 Build GPU comparison
 Build RAM evaluation
 Build performance tiers
 Build compatibility score
 Build compatibility engine
Sprint 8 — Compatibility + Core Pages
 Finish compatibility UI
 Add compatibility to Game Page
 Test across hardware combinations
 Build About page
 Build Terms of Service
 Build Privacy Policy
 Build Cookie Policy
 Build FAQ / How It Works
 Complete global footer/navigation
Sprint 9 — V1 Polish & Launch QA 🚀
 Full desktop QA
 Full mobile QA
 Search QA
 Discover QA
 Game-page QA
 Compatibility QA
 Hardware ranking QA
 API error handling
 Steam rate-limit handling
 Performance optimization
 SEO
 Accessibility
 Security review
 Production deployment
 V1 launch 🚀
🔮 Post-V1
V1.0
 ↓
Discovery Engine
 ↓
V1.5 Collections
 ↓
V2.0 Personal Nimlyx
 ↓
V2.5 Community
 ↓
V3.0 Nimlyx AI

The priority remains:

Nimlyx should first become exceptionally good at understanding games and helping people decide whether they are worth playing, buying, and running.

🎯 Nimlyx's Core Identity

Steam

"Here are the games."

Nimlyx

"Here's what they're actually like, whether they're worth your money, and whether your PC can handle them."

Analyze. Explore. Discover. 🔥