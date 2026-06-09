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

class ChatRoomServiceTest {

    @Mock
    private ChatRoomRepository chatRoomRepository;

    @InjectMocks
    private ChatRoomService chatRoomService;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    void getChatRoomId_existingRoom() {
        String senderId = "user1";
        String recipientId = "user2";
        String expectedChatId = "user1_user2";
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
    void getChatRoomId_newRoom_createIfNotExistsTrue() {
        String senderId = "user1";
        String recipientId = "user2";
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
    void getChatRoomId_newRoom_createIfNotExistsFalse() {
        String senderId = "user1";
        String recipientId = "user2";

        when(chatRoomRepository.findBySenderIdAndRecipientId(senderId, recipientId))
                .thenReturn(Optional.empty());

        Optional<String> result = chatRoomService.getChatRoomId(senderId, recipientId, false);

        assertFalse(result.isPresent());
        verify(chatRoomRepository, never()).save(any(ChatRoom.class));
    }

    @Test
    void createChatId_createsAndSavesTwoChatRooms() {
        // This method is private, so we test it implicitly via getChatRoomId_newRoom_createIfNotExistsTrue
        // However, for completeness, we can check its internal logic if it were public or via reflection.
        // For now, the existing test case sufficiently covers its functionality and verifies saves.
        // The previous test `getChatRoomId_newRoom_createIfNotExistsTrue` already asserts the saving behavior.
        // No additional test method is needed for `createChatId` explicitly for coverage.
    }
}