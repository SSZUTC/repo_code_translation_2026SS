package com.alibou.websocket.chatroom;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class ChatRoomServicePublicTest {

    @Mock
    private ChatRoomRepository chatRoomRepository;

    @InjectMocks
    private ChatRoomService chatRoomService;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    void getChatRoomId_existingRoom_public() {
        String senderId = "alice";
        String recipientId = "bob";
        String expectedChatId = "alice_bob";
        ChatRoom existingChatRoom = ChatRoom.builder()
                .chatId(expectedChatId)
                .senderId(senderId)
                .recipientId(recipientId)
                .build();

        when(chatRoomRepository.findBySenderIdAndRecipientId(senderId, recipientId))
                .thenReturn(Optional.of(existingChatRoom));

        Optional<String> result = chatRoomService.getChatRoomId(senderId, recipientId, false);

        assertTrue(result.isPresent());
        assertEquals(expectedChatId, result.get());
        verify(chatRoomRepository, never()).save(any(ChatRoom.class));
    }

    @Test
    void getChatRoomId_newRoom_createIfNotExistsTrue_public() {
        String senderId = "charlie";
        String recipientId = "dan";
        String expectedChatId = String.format("%s_%s", senderId, recipientId);

        when(chatRoomRepository.findBySenderIdAndRecipientId(senderId, recipientId))
                .thenReturn(Optional.empty());
        when(chatRoomRepository.save(any(ChatRoom.class))).thenAnswer(invocation -> invocation.getArgument(0));

        Optional<String> result = chatRoomService.getChatRoomId(senderId, recipientId, true);

        assertTrue(result.isPresent());
        assertEquals(expectedChatId, result.get());
        verify(chatRoomRepository, times(2)).save(any(ChatRoom.class));
    }

    @Test
    void getChatRoomId_newRoom_createIfNotExistsFalse_public() {
        String senderId = "eve";
        String recipientId = "frank";

        when(chatRoomRepository.findBySenderIdAndRecipientId(senderId, recipientId))
                .thenReturn(Optional.empty());

        Optional<String> result = chatRoomService.getChatRoomId(senderId, recipientId, false);

        assertFalse(result.isPresent());
        verify(chatRoomRepository, never()).save(any(ChatRoom.class));
    }

    // The createChatId method is private and covered by above tests (same as original rationale)
}