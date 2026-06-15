// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// Publisher defines the interface for publishing messages to NATS.
type Publisher interface {
	PublishPendingMessageWithAgentID(groupID string, msg *models.GroupMessage, trigger interface{}, agentID string) error
	PublishMessageCreate(msg *models.GroupMessage) error
	PublishMessageModify(msg *models.GroupMessage) error
	PublishMessageDelete(msg *models.GroupMessage) error
}

// MessageHandler handles message-related HTTP requests.
type MessageHandler struct {
	db        *gorm.DB
	publisher Publisher
	evaluator *trigger.Evaluator
	log       *logger.Logger
}

// NewMessageHandler creates a new MessageHandler.
func NewMessageHandler(db *gorm.DB, publisher Publisher, evaluator *trigger.Evaluator, log *logger.Logger) *MessageHandler {
	return &MessageHandler{
		db:        db,
		publisher: publisher,
		evaluator: evaluator,
		log:       log,
	}
}
