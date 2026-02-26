/* Games Arcade — client-side logic */
'use strict';

const socket = io();

socket.on('connect', () => {
  console.log('Games Arcade connected');
});

socket.on('state_update', (data) => {
  console.log('State update:', data);
});

socket.on('reconnect', () => {
  console.log('Reconnected to Games Arcade');
});
