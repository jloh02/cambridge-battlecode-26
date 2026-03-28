# How Matches Work
How ladder matches, Elo ratings, and the 5-game format work.

## Match format
Every match consists of 5 games. Each game is played on a different map with a different random seed. The team that wins more games wins the match.
​
### Win conditions per game
A game ends when:
| Condition |	Description
|-----------|------------
| Core destroyed | One team’s core reaches 0 HP
| Resources | After 2000 rounds, the tiebreaker sequence determines the winner
| Timeout | After 2000 rounds with equal tiebreakers — decided by coinflip
​
## Ladder
The ladder ranks all teams by Elo rating. New teams start unrated and are seeded to 1500 when they upload their first ready submission.
​
### Scheduling
Every 10 minutes, the scheduler:
1. Pairs each team with one similarly-rated opponent (greedy nearest-rating matching with small random jitter to avoid repetitive matchups)
2. Avoids rematches from the last hour
3. Submits matches to the runner infrastructure

With N teams, each cycle creates floor(N/2) matches — one match per team.
​
### Rating updates
Ratings are updated using Elo immediately after each match completes. Match outcomes use fractional scoring based on the game score (e.g., a 5-0 win counts more than a 3-2 win).

Each team has a single Elo rating that moves up or down after each match.