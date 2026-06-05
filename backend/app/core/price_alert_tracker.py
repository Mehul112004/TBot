import threading
import logging
from datetime import datetime

from app.models.db import db, PriceAlert
from app.core.telegram_queue import telegram_queue
from app.core.sse import sse_manager

logger = logging.getLogger(__name__)


class PriceAlertTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._app = None
        self._cache: dict[str, dict] = {}

    def set_app(self, app):
        self._app = app

    def rebuild_cache(self):
        if not self._app:
            return
        with self._app.app_context():
            active = PriceAlert.query.filter_by(status='ACTIVE').all()
            with self._lock:
                self._cache.clear()
                for alert in active:
                    self._cache[alert.id] = {
                        'symbol': alert.symbol,
                        'target_price': alert.target_price,
                        'direction': alert.direction,
                        'alert_type': alert.alert_type,
                        'cross_state': alert.cross_state,
                    }
        logger.info(f"PriceAlertTracker cache rebuilt with {len(self._cache)} ACTIVE alerts.")

    def add_to_cache(self, alert: PriceAlert):
        with self._lock:
            self._cache[alert.id] = {
                'symbol': alert.symbol,
                'target_price': alert.target_price,
                'direction': alert.direction,
                'alert_type': alert.alert_type,
                'cross_state': alert.cross_state,
            }

    def remove_from_cache(self, alert_id: str):
        with self._lock:
            self._cache.pop(alert_id, None)

    def check_price(self, symbol: str, price: float):
        triggered = []
        with self._lock:
            for alert_id, data in list(self._cache.items()):
                if data['symbol'] != symbol:
                    continue

                target = data['target_price']
                direction = data['direction']
                alert_type = data['alert_type']
                current_cross = data['cross_state']

                new_cross = 'WAS_ABOVE' if price > target else 'WAS_BELOW'

                crossed = False
                if direction == 'ABOVE':
                    if current_cross == 'WAS_BELOW' and new_cross == 'WAS_ABOVE':
                        crossed = True
                elif direction == 'BELOW':
                    if current_cross == 'WAS_ABOVE' and new_cross == 'WAS_BELOW':
                        crossed = True

                if new_cross != current_cross:
                    data['cross_state'] = new_cross

                if crossed:
                    triggered.append((alert_id, alert_type))

        for alert_id, alert_type in triggered:
            self._process_trigger(alert_id, alert_type, price)

    def _process_trigger(self, alert_id: str, alert_type: str, current_price: float):
        if not self._app:
            return

        with self._app.app_context():
            alert = PriceAlert.query.get(alert_id)
            if not alert or alert.status != 'ACTIVE':
                with self._lock:
                    self._cache.pop(alert_id, None)
                return

            alert.status = 'TRIGGERED'
            alert.triggered_at = datetime.utcnow()
            db.session.commit()

            if alert_type == 'ONCE':
                with self._lock:
                    self._cache.pop(alert_id, None)
            else:
                with self._lock:
                    if alert_id in self._cache:
                        self._cache[alert_id]['cross_state'] = (
                            'WAS_ABOVE' if current_price > alert.target_price else 'WAS_BELOW'
                        )

            telegram_queue.enqueue_price_alert(alert_id, current_price)
            sse_manager.publish('price_alert_triggered', alert.to_dict())
            logger.info(f"PriceAlert {alert_id} ({alert.symbol}) triggered at {current_price}")


price_alert_tracker = PriceAlertTracker()
