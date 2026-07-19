; domain_sentinel.pddl — Fixed for STRIPS Compliance
(define (domain sentinel-car)
  (:requirements :strips :typing)
  (:types vehicle)

  (:predicates
    ; System
    (parked ?v - vehicle)

    ; Damage/intrusion signals
    (damage-signal ?v - vehicle)
    (motion-outside ?v - vehicle)

    ; Cabin state
    (occupant-detected ?v - vehicle)   ; PIR + illuminance confirm
    (cabin-too-hot ?v - vehicle)
    (cabin-uv-high ?v - vehicle)
    (occupant-at-risk ?v - vehicle)    ; hot OR high-UV with occupant

    ; Response states
    (alarm-active ?v - vehicle)
    (evidence-captured ?v - vehicle)
    (cooling-engaged ?v - vehicle)
    (windows-down ?v - vehicle)
    (alert-sent ?v - vehicle)

    ; Goals
    (vehicle-secure ?v - vehicle)
    (occupant-safe ?v - vehicle)
    (cabin-secure ?v - vehicle)      ; hot cabin, no occupant → alert-only goal
  )

  ; ── DAMAGE SCENARIO ─────────────────────────────────────────

  (:action activate-damage-alarm
    :parameters (?v - vehicle)
    :precondition (and (parked ?v) (damage-signal ?v))
    :effect (alarm-active ?v)
  )

  (:action capture-damage-evidence
    :parameters (?v - vehicle)
    :precondition (and (alarm-active ?v) (damage-signal ?v))
    :effect (evidence-captured ?v)
  )

  (:action send-damage-alert
    :parameters (?v - vehicle)
    :precondition (and (alarm-active ?v) (evidence-captured ?v))
    :effect (and (alert-sent ?v) (vehicle-secure ?v))
  )

  ; ── CABIN SAFETY SCENARIO ───────────────────────────────────

  ; Split into two clean STRIPS actions to bypass the 'or' limitation
  (:action detect-occupant-heat-risk
    :parameters (?v - vehicle)
    :precondition (and (parked ?v) (occupant-detected ?v) (cabin-too-hot ?v))
    :effect (occupant-at-risk ?v)
  )

  (:action detect-occupant-uv-risk
    :parameters (?v - vehicle)
    :precondition (and (parked ?v) (occupant-detected ?v) (cabin-uv-high ?v))
    :effect (occupant-at-risk ?v)
  )

  ; Step 2a: Temperature risk → engage cooling
  (:action engage-cooling
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (cabin-too-hot ?v))
    :effect (cooling-engaged ?v)
  )

  ; Step 2a-ii: Temperature risk → roll the windows down to vent the cabin
  (:action roll-down-windows
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (cabin-too-hot ?v))
    :effect (windows-down ?v)
  )

  ; Step 2b: UV risk → send UV alert directly  
  (:action send-uv-warning
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (cabin-uv-high ?v))
    :effect (alert-sent ?v)
  )

  ; Step 3: Cooling engaged AND windows down → occupant safe
  (:action confirm-occupant-safe
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (cooling-engaged ?v) (windows-down ?v))
    :effect (occupant-safe ?v)
  )

  ; Step 3 alt: UV alert sent → occupant safe.
  ; NOTE: gated on (cabin-uv-high) on purpose. Without it, the planner would use
  ; this + the alert-only action as a cheap 3-step shortcut for a HEAT occupant
  ; and skip cooling/windows. Keeping it UV-specific forces the heat case through
  ; engage-cooling + roll-down-windows.
  (:action confirm-occupant-safe-after-uv-alert
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (cabin-uv-high ?v) (alert-sent ?v))
    :effect (occupant-safe ?v)
  )

  ; ── UNATTENDED HOT CABIN (no occupant) ──────────────────────
  ; A hot cabin with nobody inside is still worth flagging. There is no one to
  ; cool for, so the plan is alert-only — this is the path that previously had
  ; no goal to satisfy and left the planner spinning.
  (:action send-cabin-heat-alert
    :parameters (?v - vehicle)
    :precondition (and (parked ?v) (cabin-too-hot ?v))
    :effect (and (alert-sent ?v) (cabin-secure ?v))
  )
)