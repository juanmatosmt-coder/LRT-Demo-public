---
doc_id: SYN-TM-120
title: Temperature Rise versus Current
revision: A
status: active
test_type: temperature_rise
---
SYNTHETIC DOCUMENT - created for a course demonstration. Not a company procedure.

## Scope
This method measures how much energized contacts heat above the surrounding air at one or more test currents. It is used to set or confirm a current rating. It is a measurement method, not an environmental exposure; for temperature exposure use SYN-TM-110. The temperature rise bench (SYN-ELEC-TRISE) supplies up to 100 A per circuit.

## Required inputs before scheduling
The request must include the test current or the current steps in amperes; how many contacts are energized and in which pattern (one contact, a group of adjacent contacts, or all contacts); the conductor that carries the current (wire gauge and length, or board trace width and copper weight); where the thermocouples go (which contacts are monitored, how many per sample, and the location on the contact, for example at the mating interface of the hottest contact in the energized group); the ambient temperature and air condition (still air or an enclosure); and the temperature rise limit used to decide the rating, if one applies.

## Sample quantity
Test at least 3 mated samples for each configuration (energized pattern and conductor). Fewer samples need a reason in the request.

## Mounting and thermocouple access
For board-mounted connectors the request must say whether the connectors are already mounted on the test boards (soldered or pressed in) or must be mounted by the lab, who supplies the boards and which board revision, how the current is routed through the contacts (in series through the board or in parallel) and where it enters and leaves the board, and whether thermocouple access holes are already in the board under the monitored contacts or must be drilled. If the lab drills, the request gives the allowed hole location and size, or lets the lab choose and report them. For wire-terminated connectors the request must say whether the wires are already terminated and, if not, how they are to be terminated. Attaching the test board files is recommended but not required: the schematic and layout as PDF, and the full Gerber or ODB++ package by link. They show the routing, the current entry and exit, the thermocouple holes and the copper directly, and the lab reviewer checks them; when they are attached, those items need no separate written answer. The request also says whether the housing may be drilled to reach a contact; if not, the lab measures at the nearest point it can reach and reports where.

## Sample preparation
Mount each sample as it is used in the product: mated, on the specified board or with wires of the specified gauge. Attach a fine thermocouple to each monitored contact named in the request, as close to the mating interface as possible without changing how heat leaves the contact. If the request does not name the monitored contacts, the lab cannot know which contact runs hottest and must ask. A separate thermocouple measures ambient air. Test in still air, with no forced airflow.

## Test sequence
1. Measure low-level contact resistance, if requested. 2. Apply the first current step. 3. Hold until the contact temperature is stable, then record contact and ambient temperatures. 4. Repeat for each current step. 5. Stop if a temperature rise exceeds the limit or a contact reaches the rated temperature of its materials. 6. Measure low-level contact resistance again, if requested.

## Reporting
Report the temperature rise above ambient for each sample at each current, the ambient temperature, the energized pattern, the conductor details and the time to stabilize. When a limit was given, report the current at which the rise reaches it.
