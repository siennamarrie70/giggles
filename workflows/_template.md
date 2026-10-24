# Workflow: <name>

## Objective
What this workflow accomplishes, in one or two sentences.

## Required Inputs
- `<input>`: what it is and where it comes from

## Tools
- `tools/<script>.py`: what it does
  ```
  python tools/<script>.py --arg <value>
  ```

## Steps
1. Gather and validate the inputs.
2. Run the tool(s) in order. Intermediate files go to `.tmp/`.
3. Check the output before moving on.
4. Deliver the result (see Expected Outputs).

## Expected Outputs
- Deliverable: where it lands (e.g. a Google Sheet) and what it contains
- Intermediates: files in `.tmp/` (disposable)

## Edge Cases & Known Issues
Update this section as you learn: rate limits, timing quirks, unexpected behavior, and how to handle them.
- (none yet)
