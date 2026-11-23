---
doc_id: SYN-TM-101
title: Warpage Measurement During Reflow Simulation
revision: C
status: active
test_type: warpage_reflow
---
SYNTHETIC DOCUMENT - created for a course demonstration. Not a company procedure.

## Scope
This method measures out-of-plane displacement (warpage) of connector housings and electronic packages while they are heated and cooled through a reflow-simulation thermal profile. It applies to full-field optical methods such as shadow moire or digital fringe projection. Supersedes Rev B.

## Required inputs before scheduling
The request must include: (a) the thermal profile to simulate, including ramp rate, soak time and temperature, peak temperature, time above liquidus, and cooling rate; (b) the temperatures at which warpage data must be captured, which must include 25 C before heating, peak temperature, and 25 C after cooling; (c) the measurement area and datum, for example the terminal seating plane; (d) the acceptance limit, if one applies. A request without a thermal profile cannot be scheduled. The lab confirms the submitted profile against chamber limits in the equipment database before accepting the request.

## Sample preparation
Samples must be moisture-preconditioned per SYN-PR-201 before the baseline measurement. Remove packaging film and handle samples by the edges only. Apply a thin, uniform matte coating only if the surface is too reflective to measure, and record the coating used.

## Sample quantity
A minimum of 5 samples per test condition is required. Each sample must carry a unique ID traceable to its molding lot.

## Test sequence
Steps must be performed in this order: 1. Precondition samples per SYN-PR-201. 2. Measure each sample at 25 C as the baseline. 3. Heat per the submitted profile, capturing data at each requested temperature. 4. Cool to 25 C and capture the final measurement. Samples must not be run through a second profile unless the request states this explicitly.

## Measurements and sign convention
Report coplanarity as the maximum minus minimum height within the measurement area after the datum fit. Report warpage shape at each capture temperature. Positive values indicate concave-up (smile) shape; negative values indicate convex (frown) shape.

## Reporting
Results are reported per SYN-RP-301.
