"""
hrgs_scheduler
==============
Simulator and optimizer for purification scheduling strategies on
half-RGS (HRGS) based quantum repeater networks.

Package layout
--------------
models/         -- core physical data types (ErrorVector, State, …)
operations/     -- backbone and purification operation functions
schedule/       -- schedule DAG representation
evaluator.py    -- inner-loop bottom-up DAG evaluation (F, R, C, L)
cost_functions.py -- cost-function helpers
"""
