name: Feature request
description: Suggest a capability or an improvement
labels: [enhancement]
body:
  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What are you trying to do that this server does not support? Describe the problem rather than the solution.
    validations:
      required: true

  - type: textarea
    id: proposal
    attributes:
      label: Proposed change
      description: What would you like the server to do differently?
    validations:
      required: true

  - type: dropdown
    id: area
    attributes:
      label: Area
      options:
        - Triage queue
        - Compliance evaluation
        - Knowledge retrieval
        - Human-in-the-loop approval
        - Cost and budget
        - Transport or protocol conformance
        - Deployment
        - Documentation
        - Other
    validations:
      required: true

  - type: checkboxes
    id: contract-accuracy
    attributes:
      label: Accuracy
      options:
        - label: >
            If this changes what an existing tool claims to do, I will update the tool
            description and the README so neither overstates the behaviour.
