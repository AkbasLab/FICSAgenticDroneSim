"""Executing plans: the open-loop runner, the team flight, and what they measure.

`executor`  DroneRunner and fly_plans -- the agent's flying decisions
`ground`    the session's ground reference, which every altitude depends on
`contacts`  classifying what a collision was with
`monitor`   separation and collision polling during a flight
`navigation` altitude above ground to NED and back, headings, tolerance,
            coverage paths -- the skill layer's only sign handling (Phase 3)
`skills`    the eleven mission-level skills, their contracts, SkillResult (Phase 3)
"""
