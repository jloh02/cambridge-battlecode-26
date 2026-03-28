# Project Summary: Cambridge Battlecode 2026

## Overview
This repository is for the **Battlecode 2026 competition**, a programming contest where participants develop bots to compete in a strategic, turn-based game. The game involves resource management, unit control, and strategic planning to outmaneuver opponents on a variety of maps.

### Key Components
- **Bots**: Custom AI implementations for the game, located in the `bots/` directory.
- **Maps**: Game maps (`.map26` files) are stored in the `maps/` directory.
- **Documentation**: Detailed game rules, APIs, and mechanics are in the `docs/` folder.
- **OpenSpec Workflow**: The `openspec/` directory manages structured workflows for proposing, implementing, and verifying changes.

## How to Play

### Objective
The goal is to outscore your opponent by managing resources, building units, and strategically controlling the map. Players write code to automate their bots' behavior.

### Game Mechanics
1. **Resources**:
   - **Titanium (Ti)**: Used to build units and structures.
   - **Axionite**: Must be refined before use; raw Axionite is destroyed if delivered to the core or turrets.

2. **Units**:
   - **Builder Bots**: The only mobile unit. They can construct buildings, heal, and attack.
     - Cost: 50 Ti.
     - Healing: 1 Ti for 4 HP.
     - Attack: 2 Ti for 2 damage (on the same tile).
   - **Sentinels**: Stationary units with high damage output.
     - Reload: 2 rounds.
     - Damage: 10.
     - Ammo: 5 per shot.

3. **Structures**:
   - **Bridges**: Provide 5% scaling but cost 20 Ti.
   - **Conveyors**: Facilitate movement but lack scaling.

4. **Global Rules**:
   - Maximum of 50 units per team.
   - Raw Axionite is destroyed if not refined.

### Steps to Play
1. **Set Up**:
   - Clone the repository.
   - Install dependencies using `pip install -r requirements.txt`.

2. **Write Your Bot**:
   - Implement your bot logic in the `bots/` directory.
   - Use the `starter/` bot as a template.

3. **Test Your Bot**:
   - Use the provided maps in the `maps/` directory.
   - Run simulations to test your bot's performance.

4. **Submit Your Bot**:
   - Follow competition guidelines to submit your bot for matches.

### Strategy Tips
- Balance resource allocation between building units and scaling structures.
- Use builder bots strategically for healing and attacking.
- Optimize map control to deny resources to your opponent.

## Additional Resources
- Refer to the `docs/` folder for detailed game rules and APIs.
- Use the `openspec/` workflow for proposing and implementing changes.

---
This document provides a high-level summary of the repository and gameplay. For more details, consult the documentation files in the `docs/` folder.