// Единственное место, которое меняется при переносе (локально / сервер / Dynamics 365 web resource).
export const CONFIG = {
  // true — всё работает на моках из ./mocks и localStorage, бэкенд не нужен.
  USE_MOCKS: true,
  // Базовый адрес бэкенда. Без завершающего слэша.
  API_BASE: 'http://localhost:8000/api',
  // Набор по умолчанию для импорта от организаторов.
  DEFAULT_GROUP_ID: 'DEV',
};
