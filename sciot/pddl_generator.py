def generate_problem(damage_signal, motion_outside, occupant_detected,
                     cabin_too_hot, cabin_uv_high,
                     output_path="problem_sentinel.pddl"):
    init_facts = ["(parked car1)"]
    
    if damage_signal:     init_facts.append("(damage-signal car1)")
    if motion_outside:    init_facts.append("(motion-outside car1)")
    if occupant_detected: init_facts.append("(occupant-detected car1)")
    if cabin_too_hot:     init_facts.append("(cabin-too-hot car1)")
    if cabin_uv_high:     init_facts.append("(cabin-uv-high car1)")

    goals = []
    if damage_signal or motion_outside:
        goals.append("(vehicle-secure car1)")
    if occupant_detected and (cabin_too_hot or cabin_uv_high):
        goals.append("(occupant-safe car1)")
        
    if not goals:
        goals.append("(vehicle-secure car1)") 

    # Explicitly handle block wrapping
    if len(goals) > 1:
        goal_str = f"(and\n        " + "\n        ".join(goals) + "\n    )"
    else:
        goal_str = goals[0]

    problem = f"""(define (problem sentinel-problem)
  (:domain sentinel-car)
  (:objects car1 - vehicle)
  (:init
    {chr(10).join("    " + f for f in init_facts)}
  )
  (:goal {goal_str})
)
"""
    with open(output_path, "w") as f:
        f.write(problem)
    return output_path