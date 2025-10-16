// server.js
import express from 'express';
import bodyParser from 'body-parser';
import path from 'path';
import { fileURLToPath } from 'url';
// import { validateInitData } from './utils/validation.js'; // В реальном проекте вынесите валидацию

const app = express();
const PORT = process.env.PORT || 3000;

// Используем ES Module пути
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

app.use(bodyParser.json());
app.use(express.static(path.join(__dirname, 'public'))); // Обслуживаем фронтенд

// --- ВРЕМЕННАЯ БД В ПАМЯТИ ---
// !!! ПОТЕРЯЕТ ДАННЫЕ ПРИ ПЕРЕЗАПУСКЕ !!!
const inMemoryDb = {}; 
// Структура: { userId: { stars: 0, last_chest_open: 0, referrer_id: null, ref_earnings: [] } }

// ----------------------------------------------------------------------
// ВАЖНО: Функции-заглушки для валидации и получения ID
// В реальном проекте используйте @telegram-apps/init-data-node
// для безопасной валидации с вашим BOT_TOKEN.
function getUserIdFromInitData(authHeader) {
    // В реальном проекте: Проверяем authHeader (initData) с BOT_TOKEN 
    // и возвращаем user.id. 
    // Здесь просто берем userId из параметра (НЕБЕЗОПАСНО ДЛЯ ПРОДАКШНА)
    const data = new URLSearchParams(authHeader);
    return data.get('user_id') || 'guest_user'; // Заглушка
}
// ----------------------------------------------------------------------

// Маршрут для получения данных пользователя
app.get('/api/user/data', async (req, res) => {
    const userId = getUserIdFromInitData(req.query.initData);

    if (!inMemoryDb[userId]) {
        // Создание нового пользователя и логика регистрации реферала
        const referrerId = req.query.ref_id;
        
        let newUser = { 
            stars: 0, 
            last_chest_open: 0, 
            referrer_id: referrerId || null, 
            ref_earnings: [] 
        };
        inMemoryDb[userId] = newUser;
        
        // 1. Начисление 2 звезд рефереру за регистрацию
        if (referrerId && inMemoryDb[referrerId]) {
            inMemoryDb[referrerId].stars += 2;
            
            // Добавляем запись в список доходов реферера
            const refEntry = inMemoryDb[referrerId].ref_earnings.find(e => e.id === userId);
            if (!refEntry) {
                inMemoryDb[referrerId].ref_earnings.push({ 
                    id: userId, 
                    username: `User_${userId}`, 
                    total_earned: 2 
                });
            } else {
                refEntry.total_earned += 2;
            }
        }
    }

    const userData = inMemoryDb[userId];
    
    // Получаем список рефералов и их заработок для текущего пользователя
    const referralsData = inMemoryDb[userId].ref_earnings;
    
    res.json({
        userId,
        stars: userData.stars,
        last_chest_open: userData.last_chest_open,
        referrals: referralsData
    });
});


// Маршрут для открытия сундука
app.post('/api/chest/open', async (req, res) => {
    const userId = getUserIdFromInitData(req.body.initData);
    const user = inMemoryDb[userId];

    if (!user) {
        return res.status(401).json({ message: "Пользователь не найден." });
    }

    const lastOpen = user.last_chest_open || 0;
    const oneDay = 24 * 60 * 60 * 1000;
    
    // Проверка, прошел ли 1 день
    if (Date.now() - lastOpen < oneDay) {
        const remainingTimeMs = oneDay - (Date.now() - lastOpen);
        const hours = Math.floor(remainingTimeMs / (60 * 60 * 1000));
        const minutes = Math.floor((remainingTimeMs % (60 * 60 * 1000)) / (60 * 1000));
        return res.status(400).json({ message: `Отмычка восстановится через ${hours} ч. ${minutes} мин.` });
    }

    // Заработок звезд (случайное число от 1 до 5)
    const starsEarned = Math.floor(Math.random() * 5) + 1; 
    
    // 1. Обновить данные пользователя
    user.stars += starsEarned;
    user.last_chest_open = Date.now();

    // 2. Логика начисления 10% рефереру
    if (user.referrer_id && inMemoryDb[user.referrer_id]) {
        const commission = Math.floor(starsEarned * 0.10 * 100) / 100; // Точность до 2 знаков
        
        inMemoryDb[user.referrer_id].stars += commission;

        // Обновить запись в ref_earnings реферера
        const referrerId = user.referrer_id;
        const refEntry = inMemoryDb[referrerId].ref_earnings.find(e => e.id === userId);
        if (refEntry) {
            refEntry.total_earned += commission;
        }
    }

    res.json({ 
        message: `Вы взломали сундук и получили ${starsEarned} ⭐!`, 
        newStars: user.stars 
    });
});


app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});
