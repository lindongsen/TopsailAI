Feature: Endpoint query permission matrix

  The Server authenticates a caller and forwards the request without deciding
  whether the operation is permitted. The Endpoint decides, from its own policy
  directory, before it consults the adapter. A refusal therefore has to be
  distinguishable from every other way a read can fail: an adapter that cannot
  answer, an Endpoint that is offline, and a provider that returned an error all
  produce a different code.

  Each scenario presents two credentials that both exist in the policy directory.
  One holds the scope that covers the operation, the other holds an unrelated
  scope. A refusal is therefore caused by the missing operation and never by a
  credential the Endpoint does not know.

  Scenario: The model catalog read is authorized by the view scope
    Given a real cluster whose endpoint policy separates view from read output
    When the model catalog is read with the view credential
    Then the model catalog read is allowed and reaches the provider
    When the model catalog is read with the read output credential
    Then the model catalog read is refused with policy denied and exposes nothing

  Scenario: The launch options read is authorized by the view scope
    Given a real cluster whose endpoint policy separates view from read output
    When the launch options is read with the view credential
    Then the launch options read is allowed and reaches the provider
    When the launch options is read with the read output credential
    Then the launch options read is refused with policy denied and exposes nothing

  Scenario: The history read is authorized by the view scope
    Given a real cluster whose endpoint policy separates view from read output
    When the history is read with the view credential
    Then the history read is allowed and reaches the provider
    When the history is read with the read output credential
    Then the history read is refused with policy denied and exposes nothing

  Scenario: The messages read is authorized by the view scope
    Given a real cluster whose endpoint policy separates view from read output
    When the messages is read with the view credential
    Then the messages read is allowed and reaches the provider
    When the messages is read with the read output credential
    Then the messages read is refused with policy denied and exposes nothing

  Scenario: The output snapshot read is authorized by the read output scope
    Given a real cluster whose endpoint policy separates view from read output
    When the output snapshot is read with the read output credential
    Then the output snapshot read is allowed and reaches the provider
    When the output snapshot is read with the view credential
    Then the output snapshot read is refused with policy denied and exposes nothing

  Scenario: The output follow read is authorized by the read output scope
    Given a real cluster whose endpoint policy separates view from read output
    When the output follow is read with the read output credential
    Then the output follow read is allowed and reaches the provider
    When the output follow is read with the view credential
    Then the output follow read is refused with policy denied and exposes nothing
