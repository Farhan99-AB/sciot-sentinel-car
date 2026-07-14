(define (problem sentinel-problem)
  (:domain sentinel-car)
  (:objects car1 - vehicle)
  (:init
        (parked car1)
    (cabin-too-hot car1)
  )
  (:goal (cabin-secure car1))
)
