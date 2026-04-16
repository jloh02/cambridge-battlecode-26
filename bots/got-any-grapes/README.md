# got-any-grapes

`got-any-grapes` is the active experimental bot line. It is built for the real
Cambridge execution model: every unit has private Python state, and markers are
the only legal inter-unit communication.

The bot is currently an economy-pressure strategy with opportunistic assault and
local defense. It is not promotion-safe yet: remote timing pressure and
zero-output games are still the main blockers.

## Current Strategy

The strategic core is titanium-first direct-core economy.

Economy builders try to:

- find nearby titanium quickly
- place harvesters adjacent to ore
- build a return lane to the core for close harvesters
- merge into existing friendly logistics only when that is cheaper or visibly
  necessary
- recheck and retile friendly harvesters whose routes were destroyed
- recover from stalls with temporary obstacles, target blacklists, and
  pathfinding resets

The direct-core return is intentional. It is the main edge against pure economy
opponents such as `jon-6`, and should not be replaced by broad threat reroutes
or generic merge penalties.

## Assault And Pressure

Diagonal spawn-slot builders start in assault mode. They use symmetry and
visible enemy harvesters to find pressure targets, then try to build sentinels
around enemy harvesters or contest enemy logistics.

Assault builders:

- use bounded opening escape from the core shell
- cache scout targets and committed assault sites
- publish assault claim markers to reduce duplicate anchor pressure
- retire anchors that are captured, blocked, saturated, or stale
- yield back to economy after long periods without meaningful progress

Non-assault builders can also opportunistically hijack visible enemy harvester
outlets. This is local and visibility-based; it does not assume shared Python
state.

Hijack is intentionally bounded around visible enemy harvesters. It contests or
seals an enemy harvester outlet, then can tile back from a secured outlet. A
broader visible-supply-line sabotage variant and a fed-sentinel outlet variant
were tested and rejected because they over-peeled flex builders or poisoned the
secured hijack site.

## Core And Lane Defense

The bot now has a narrow defensive override for offensive matchups. The current
model separates two offensive profiles:

- rush pressure, where an enemy tries to reach or damage the core before the
  economy is ready
- suppression pressure, where an enemy tries to sit on or near the titanium
  lane and keep harvesters from delivering

Non-assault economy/explorer builders near the own core will interrupt greed
when they visibly detect an enemy builder or turret in the core-defense radius.
They spend titanium on a local sentinel aimed at the assailant.

The initial explorer and other non-assault economy builders can also defend the
first near-core harvester or conveyor lane. This lane defense is evidence-gated:
enemy builders must be close to a visible friendly economy asset that already
has visible damage. Non-builder turrets near the asset still count as immediate
pressure. Visible local sentinels are capped so the response does not turn every
scout contact into a turret farm.

Active `TILING_BACK` builders are left alone so the first working titanium lane
is not peeled apart while it is under construction.

This is intentionally bounded:

- no global defense manager
- no shared Python state
- no marker dependency
- no hard reroute away from direct-core lanes
- no full-grid defense scan
- final legality still goes through `can_build_sentinel`

Sentinel firing policy is also context-scoped. A defensive sentinel near a
visible friendly core should remove the assaulting enemy builder first, then
shoot guns, then fall back to the normal logistics/core target order. Forward
hijack and assault sentinels should not globally switch to builder-first
targeting, because that can stop the pressure on enemy logistics and collapse
the sabotage plan.

## Implementation Map

- `core_bot.py`: spawning policy, opening assault wave, bonus assault gating
- `builder_bot.py`: top-level builder mode dispatch and fast-perception cadence
- `perception.py`: visible-tile memory, marker parsing, ore/enemy/transport
  inference, connected-conveyor tracking
- `navigation.py`: bounded A*, resumable path state, micro-plans, assault
  movement, temporary obstacle recovery
- `mode_finding_ore.py`: ore selection, harvester placement, direct-core entry
  into `TILING_BACK`
- `mode_tiling_back.py`: return-target selection, conveyor/bridge construction,
  pending-build handling, stall fallback
- `mode_assaulting.py`: enemy inference, scout targets, assault sites, sentinel
  execution, assault claims
- `mode_hijacking.py`: visible enemy outlet contesting and hijack tiling
- `defense.py`: local core and lane-defense sentinel override
- `sentinel_bot.py`: sentinel target selection and firing

## MAE Framework

We use MAE to separate failure analysis into three layers.

Mechanistic: runtime and implementation cost. Examples here are broad grid
scans, repeated SDK calls, A* churn, marker scan/removal overhead, and excessive
per-turn allocations. Mechanistic fixes should preserve behavior while reducing
work.

Algorithmic: local decision quality. Examples are ore target selection,
direct-core versus pipeline return choice, stall recovery, route repair,
defensive sentinel placement, and assault site scoring.

Emergent: team-level behavior that arises from private unit policies. Examples
are builder clumping, duplicate assault anchors, marker poisoning, overbuilding
sentinels, core-port saturation, and economy builders abandoning the first lane
too early.

The current development priority is:

1. remote safety and hot-path cost
2. reliable first titanium lane
3. local defense against early assailants
4. reduced zero-output games
5. only then broader marker coordination and axionite/foundry work

## Current Known Issues

- Reduced TILING_BACK fast scan radius (9 → 2) to cut tile SDK calls on
  established economy turns. Leeroy timing improved ~14pp; aggregate neutral.
- Strengthened hijack readiness gate to require 4+ connected transports with
  positive source load plus Ti reserves before peeling economy builders.
- Added `scan_micro()` perception function (unit-only, not currently called)
  for future use.
- Remote TLE pressure remains unresolved.
- Local replay `execTimeUs` can be zero, so local timing analysis is incomplete.
- Assault claim markers are useful but can poison construction space; bluntly
  disabling or slowing them has regressed local benchmarks.
- Core delivery often concentrates through only two or three final ports.
- Small-loop, low-progress, and travel-without-build signals still appear in
  many games.
- Local evidence says generic "shoot builders first" defense is too broad:
  it must be scoped to actual core-defense context or it can break forward
  hijack pressure.
- Axionite/foundry/refinery strategy is intentionally deferred until titanium
  economy and timing are reliable.
