package dev.factory.operations.api;

import java.util.*;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import static dev.factory.operations.domain.ReadSupport.map;

@RestControllerAdvice
@Profile("!bootstrap")
public class ApiErrors {
    @ExceptionHandler(ApiProblem.class) public ResponseEntity<Map<String,Object>> problem(ApiProblem problem) {return error(problem.http,problem.code);}
    @ExceptionHandler(DataAccessException.class) public ResponseEntity<Map<String,Object>> database(DataAccessException problem) {return error(503,"DB_UNAVAILABLE");}
    private ResponseEntity<Map<String,Object>> error(int http,String code) {return ResponseEntity.status(http).cacheControl(CacheControl.noStore()).body(map("schemaVersion",1,"code",code,"message",switch(code){case "DB_UNAVAILABLE"->"데이터 저장소를 확인해야 합니다.";case "VIEW_NOT_READY"->"관제 묶음이 준비되지 않았습니다.";case "CURSOR_EXPIRED"->"조회 시간이 만료되었습니다. 새 조회를 시작하세요.";case "CURSOR_MISMATCH"->"조회 조건이 이전 페이지와 다릅니다.";case "RUN_NOT_FOUND","RESOURCE_NOT_FOUND"->"요청한 기록이 없습니다.";default->"요청 형식과 조건을 확인하세요.";} ,"requestId",UUID.randomUUID().toString()));}
}
