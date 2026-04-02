# orange_v1

Model no. 1 from @BenyAlbatross

Branch baseline: `policy_fsm_v3`, with an orange-specific enemy-base assault layer.

Current strategy delta:
- Replaces the earlier core-centric stolen-ammo siege stack with a harvester-ring assault.
- Assault builders now look for the visible enemy titanium harvester closest to the enemy base, then try to place direct-fed sentinels on the cardinal ring around that harvester.
- Ring sentinels prioritize enemy turrets first, then enemy conveyors, then the enemy core.
- Midgame spawn pressure keeps enough builders alive for a fixed four-attacker assault pool once the home economy is bootstrapped.

Intended strengths:
- Simpler enemy-base combat plan with fewer mutually conflicting subgoals.
- Better chance of actually converting enemy-base contact into live sentinels and shots.
- Stronger local starvation pressure on enemy logistics around the chosen harvester hub.

Intended weaknesses:
- The bot now commits harder to one visible enemy harvester objective at a time.
- A bad harvester choice or overcommitted ring can still waste builder time near the enemy base.
- Direct-fed harvester rings are local pressure tools, not guaranteed core-kill structures on every map.

Known tradeoffs and unknowns:
- One harvester cannot reliably sustain four sentinels forever, so the build order still stages the first two ring sites before filling the rest.
- The rewrite should improve actual combat activity first; benchmark strength versus other candidates still needs measurement.
