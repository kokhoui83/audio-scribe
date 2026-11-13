Feature: A robust queue
  Failures, crashes and restarts never lose a file and never loop forever.

  @FR-32
  Scenario: A transient failure is retried after a delay
    Given a queued recording "call.mp3"
    And the speech recogniser will fail 1 time with "out of memory"
    When the worker processes the queue
    Then the job for "call.mp3" is queued
    And the job for "call.mp3" has the error "out of memory"
    When the worker processes the queue
    Then the job for "call.mp3" is queued
    When 30 seconds pass
    And the worker processes the queue
    Then the job for "call.mp3" is done
    And the job for "call.mp3" took 2 attempts

  @FR-32 @FR-35
  Scenario: A file that keeps failing is given up after the last attempt
    Given a queued recording "call.mp3"
    And the speech recogniser will fail 3 times with "out of memory"
    When the worker processes the queue
    And 30 seconds pass
    And the worker processes the queue
    And 60 seconds pass
    And the worker processes the queue
    Then the job for "call.mp3" is failed
    And the job for "call.mp3" took 3 attempts
    And the failed folder contains "call.mp3"
    And the failed folder contains "call.mp3.error.txt" explaining "out of memory"
    And no staged files remain

  @FR-33 @FR-35
  Scenario: A file that is not audio fails immediately
    Given a queued file "broken.mp3" that cannot be decoded
    When the worker processes the queue
    Then the job for "broken.mp3" is failed
    And the job for "broken.mp3" took 1 attempt
    And the failed folder contains "broken.mp3"

  @FR-34
  Scenario: The job of a crashed worker is returned to the queue
    Given a queued recording "call.mp3"
    And a worker crashes while processing "call.mp3"
    When 120 seconds pass
    And the housekeeper runs
    Then the job for "call.mp3" is processing
    When 1 second passes
    And the housekeeper runs
    Then the job for "call.mp3" is queued
    When the worker processes the queue
    Then the job for "call.mp3" is done
    And the job for "call.mp3" took 2 attempts

  @FR-34 @FR-35
  Scenario: A file that keeps crashing its worker is given up
    Given a queued recording "poison.mp3"
    And a worker crashes while processing "poison.mp3"
    And 121 seconds pass
    And the housekeeper runs
    And a worker crashes while processing "poison.mp3"
    And 121 seconds pass
    And the housekeeper runs
    And a worker crashes while processing "poison.mp3"
    When 121 seconds pass
    And the housekeeper runs
    Then the job for "poison.mp3" is failed
    And the failed folder contains "poison.mp3"
    And the failed folder contains "poison.mp3.error.txt" explaining "stopped responding"

  @FR-34
  Scenario: A slow job that keeps reporting progress keeps its lease
    Given a queued recording "long.mp3"
    And transcribing "long.mp3" takes 10 minutes
    When the worker processes the queue while the housekeeper runs every minute
    Then the job for "long.mp3" is done
    And the job for "long.mp3" took 1 attempt

  @FR-36
  Scenario: Stopping the worker returns its job without spending an attempt
    Given a queued recording "call.mp3"
    And the worker is asked to stop while transcribing
    When the worker processes the queue
    Then the job for "call.mp3" is queued
    And the job for "call.mp3" took 0 attempts
    And the output folder is empty

  @FR-40
  Scenario: A job cancelled while it is being transcribed is abandoned
    Given a queued recording "call.mp3"
    And the job is cancelled while it is being transcribed
    When the worker processes the queue
    Then the job for "call.mp3" is cancelled
    And the output folder is empty

  @FR-38 @FR-42
  Scenario: A worker that cannot load its models takes no jobs and says why
    Given a queued recording "call.mp3"
    And the speech models cannot be loaded because "HF_TOKEN is not set"
    When the worker processes the queue
    Then the job for "call.mp3" is queued
    And the job for "call.mp3" took 0 attempts
    And the worker reports the error "HF_TOKEN is not set"
    When the speech models become available
    And the worker processes the queue
    Then the job for "call.mp3" is done
    And the worker reports that it is ready
