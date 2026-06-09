package com.alibou.websocket.chat;

import com.alibou.websocket.chat.ChatMessage;
import com.alibou.websocket.chat.ChatController;
import com.alibou.websocket.chat.ChatMessageService;
import com.alibou.websocket.chat.ChatNotification;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class ChatControllerTest {

    @Mock
    private SimpMessagingTemplate messagingTemplate;

    @Mock
    private ChatMessageService chatMessageService;

    @InjectMocks
    private ChatController chatController;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    void processMessage_sendsAndSavesMessage() {
        ChatMessage chatMessage = ChatMessage.builder()
                .senderId("user1")
                .recipientId("user2")
                .content("Hello")
                .build();
        chatMessage.setId("msg1"); // Assign an ID to simulate saving

        when(chatMessageService.save(any(ChatMessage.class))).thenReturn(chatMessage);

        chatController.processMessage(chatMessage);

        verify(chatMessageService, times(1)).save(chatMessage);
        verify(messagingTemplate, times(1)).convertAndSendToUser(
                eq("user2"),
                eq("/queue/messages"),
                any(ChatNotification.class)
        );
    }

    @Test
    void findChatMessages_returnsMessages() {
        String senderId = "user1";
        String recipientId = "user2";
        List<ChatMessage> mockMessages = Arrays.asList(
                ChatMessage.builder().senderId(senderId).recipientId(recipientId).content("Hi").build(),
                ChatMessage.builder().senderId(recipientId).recipientId(senderId).content("Hello").build()
        );

        when(chatMessageService.findChatMessages(senderId, recipientId)).thenReturn(mockMessages);

        ResponseEntity<List<ChatMessage>> response = chatController.findChatMessages(senderId, recipientId);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(2, response.getBody().size());
        assertEquals(mockMessages, response.getBody());
        verify(chatMessageService, times(1)).findChatMessages(senderId, recipientId);
    }
}