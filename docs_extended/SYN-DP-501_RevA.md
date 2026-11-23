---
doc_id: SYN-DP-501
title: Warpage Data Processing
revision: A
status: active
test_type: reporting
---
SYNTHETIC DOCUMENT - created for a course demonstration. Not a company procedure.

## Scope
This method describes how the lab processes raw height maps into coplanarity and shape results. It is applied by the lab after measurement.

## Masking
Mask regions outside the measurement area before fitting. Holes, slots and label areas inside the measurement area are masked when they produce invalid points.

## Datum fit
Fit the datum plane by least squares to the points in the datum region. When no datum region is specified, the lab uses the whole measurement area.

## Filtering and outliers
Apply a median filter with a 5 by 5 pixel window. Remove points more than 4 standard deviations from the local mean and report the number removed.

## Coplanarity calculation
Calculate coplanarity as the maximum minus minimum height of the remaining points relative to the fitted datum.

## Data review
A second technician reviews every result before release. Results with more than 5 percent of points removed are flagged for review by the requester.
