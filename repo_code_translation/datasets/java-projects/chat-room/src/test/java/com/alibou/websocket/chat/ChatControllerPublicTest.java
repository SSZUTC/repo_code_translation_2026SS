package com.alibou.websocket.chat;

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

class ChatControllerPublicTest {

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
    void processMessage_sendsAndSavesMessage_public() {
        ChatMessage chatMessage = ChatMessage.builder()
                .senderId("alice")
                .recipientId("bob")
                .content("Hi Bob!")
                .build();
        chatMessage.setId("msg42"); // Assign a public test ID

        when(chatMessageService.save(any(ChatMessage.class))).thenReturn(chatMessage);

        chatController.processMessage(chatMessage);

        verify(chatMessageService, times(1)).save(chatMessage);
        verify(messagingTemplate, times(1)).convertAndSendToUser(
                eq("bob"),
                eq("/queue/messages"),
                any(ChatNotification.class)
        );
    }

    @Test
    void findChatMessages_returnsMessages_public() {
        String senderId = "charlie";
        String recipientId = "dan";
        List<ChatMessage> mockMessages = Arrays.asList(
                ChatMessage.builder().senderId(senderId).recipientId(recipientId).content("Good morning").build(),
                ChatMessage.builder().senderId(recipientId).recipientId(senderId).content("Hey Charlie!").build()
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