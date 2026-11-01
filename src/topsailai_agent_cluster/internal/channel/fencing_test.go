package channel

import "testing"

func TestFenceRejectsOldGeneration(t *testing.T) {
	fence := NewFence()
	old := fence.Acquire("e1")
	current := fence.Acquire("e1")
	if current <= old {
		t.Fatalf("generation did not advance: old=%d current=%d", old, current)
	}
	if err := fence.Check("e1", old); err != ErrFenced {
		t.Fatalf("old generation error = %v", err)
	}
	if err := fence.Check("e1", current); err != nil {
		t.Fatalf("current generation rejected: %v", err)
	}
}
