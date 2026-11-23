---
doc_id: SYN-TM-130
title: Low-Level Contact Resistance (LLCR)
revision: A
status: active
test_type: llcr
---
SYNTHETIC DOCUMENT - created for a course demonstration. Not a company procedure.

## Scope
This method measures the resistance of mated contacts at dry-circuit levels, low enough that the measurement does not break through surface films. It is usually a readout before and after an exposure (durability, thermal cycling, humidity, gas corrosion), so the result is the change in resistance. The low-level contact resistance system (SYN-ELEC-LLCR) applies at most 20 mV open circuit and 100 mA, on up to 40 channels.

## Required inputs before scheduling
The request must include: which contacts are measured (positions, and how many per sample); where the measurement points are (where the current and voltage-sense leads attach on each side of the mated pair, for example at the board pads or the wire crimps), and whether the bulk resistance of the terminations is to be subtracted; how the samples are mounted (on test boards or wire-terminated); when readouts are taken (initial, and after which exposures or cycle counts); and the acceptance limit, usually the largest allowed change from the initial reading in milliohms, if one applies.

## Mounting and measurement points
For board-mounted connectors the request says whether the connectors are already mounted on the test boards and which board revision, and gives the pad or via used as each measurement point. Attaching the test board files is recommended but not required: the schematic and layout as PDF show the routing and measurement points directly, and the lab reviewer checks them. For wire-terminated connectors the request gives the measurement point on each wire, measured from the crimp, so the bulk resistance stays the same at every readout.

## Sample quantity
Measure at least 3 mated samples per configuration. Fewer samples need a reason in the request.

## Test sequence
1. Mate the samples, if they are not already mated. 2. Take the initial reading on every listed position. 3. Run the exposure or sequence named in the request. 4. Take a reading at each requested point, at the same measurement points and in the same order. 5. Report the change from the initial reading.

## Reporting
Report, for every position and readout, the resistance and the change from the initial reading; the measurement points and whether bulk resistance was subtracted; the test current and open-circuit voltage; and any position that exceeded the limit.
