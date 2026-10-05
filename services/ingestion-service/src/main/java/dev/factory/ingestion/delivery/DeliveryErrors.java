package dev.factory.ingestion.delivery;

import java.util.*;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import static dev.factory.ingestion.delivery.DeliveryStore.map;

@RestControllerAdvice(assignableTypes=DeliveryController.class)
@Profile("!bootstrap")
public class DeliveryErrors {
    @ExceptionHandler(DeliveryProblem.class) public ResponseEntity<Map<String,Object>> problem(DeliveryProblem p){return error(p.http,p.code);}
    @ExceptionHandler(DataAccessException.class) public ResponseEntity<Map<String,Object>> database(DataAccessException failure){return error(503,"DB_UNAVAILABLE");}
    private ResponseEntity<Map<String,Object>> error(int http,String code){return ResponseEntity.status(http).cacheControl(CacheControl.noStore()).body(map("protocolVersion",1,"code",code,"message",switch(code){case "RUN_NOT_FOUND"->"등록된 전달 실행이 없습니다.";case "DB_UNAVAILABLE"->"전달 저장소를 확인해야 합니다.";case "RESUME_NOT_ALLOWED"->"이 상태는 재개할 수 없습니다.";case "CURSOR_MISMATCH"->"다음 전달 순번이 요청과 다릅니다.";default->"요청 양식과 조건을 확인하세요.";},"requestId",UUID.randomUUID().toString()));}
}
