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
    (alert-sent ?v - vehicle)

    ; Goals
    (vehicle-secure ?v - vehicle)
    (occupant-safe ?v - vehicle)
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

  ; Step 2b: UV risk → send UV alert directly  
  (:action send-uv-warning
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (cabin-uv-high ?v))
    :effect (alert-sent ?v)
  )

  ; Step 3: Cooling engaged → occupant safe
  (:action confirm-occupant-safe
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (cooling-engaged ?v))
    :effect (occupant-safe ?v)
  )

  ; Step 3 alt: UV alert sent → occupant safe
  (:action confirm-safe-after-uv-alert
    :parameters (?v - vehicle)
    :precondition (and (occupant-at-risk ?v) (alert-sent ?v))
    :effect (occupant-safe ?v)
  )
)