from app.domain.models import PackedBox, PackingInstructionStep, Product


def build_instructions(
    box: PackedBox,
    products: dict[str, Product],
) -> tuple[PackingInstructionStep, ...]:
    steps = [
        PackingInstructionStep(
            step=0,
            action="prepare_box",
            box_id=box.id,
            message=(
                f"Возьмите коробку «{box.name}» ({box.id}), "
                f"внутренние размеры {box.length} × {box.width} × {box.height} мм. "
                "Передний левый нижний угол — начало координат."
            ),
        )
    ]
    for placement in sorted(box.placements, key=lambda placement: placement.step):
        product = products[placement.product_id]
        point, size = placement.position, placement.dimensions
        steps.append(
            PackingInstructionStep(
                step=placement.step,
                action="place_item",
                box_id=box.id,
                item_instance_id=placement.item_instance_id,
                product_id=placement.product_id,
                position=point,
                dimensions=size,
                orientation=placement.orientation,
                message=(
                    f"Возьмите «{product.name}», единицу {placement.item_instance_id}. "
                    f"Ориентируйте: {size.length} мм вправо, {size.width} мм вглубь, "
                    f"{size.height} мм вверх ({placement.orientation}). "
                    f"Поместите нижний передний левый угол на {point.x} мм вправо, "
                    f"{point.y} мм вглубь и {point.z} мм от дна коробки."
                ),
            )
        )
    steps.append(
        PackingInstructionStep(
            step=len(box.placements) + 1,
            action="close_box",
            box_id=box.id,
            message=(
                f"Проверьте {len(box.placements)} ед. товара в коробке {box.id}. "
                f"Вес товаров — {box.total_weight} г из допустимых {box.max_weight} г. "
                "Закройте коробку."
            ),
        )
    )
    return tuple(steps)
